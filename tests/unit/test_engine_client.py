from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

import httpx
import pytest

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import BinaryRef, NodeOutput
from app.providers.auth import AuthResult, CredentialKind
from app.services.dag_scheduler import DAGNode
from app.services.engine_client import EngineClient, make_node_executor
from app.services.ssrf_guard import SsrfBlockedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSettings:
    ocr_engine_url = "http://localhost:9001"
    vlm_engine_url = "http://localhost:9002"
    text_engine_url = "http://localhost:9003"
    markitdown_engine_url = "http://localhost:9004"
    layout_detection_engine_url = "http://localhost:9005"
    image_enhancement_engine_url = "http://localhost:9006"
    image_rotation_engine_url = "http://localhost:9007"


def _ok_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def _error_response(status: int, body: str = "error") -> httpx.Response:
    return httpx.Response(status, text=body)


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------


class TestResolveUrl:
    def test_known_engine_type(self):
        client = EngineClient(settings=_FakeSettings())
        url = client._resolve_url("engine/ocr")
        assert url == "http://localhost:9001"

    def test_known_processor_type(self):
        client = EngineClient(settings=_FakeSettings())
        url = client._resolve_url("processor/layout_detection")
        assert url == "http://localhost:9005"

    def test_unknown_type_raises(self):
        client = EngineClient(settings=_FakeSettings())
        with pytest.raises(ValueError, match="Unknown node type"):
            client._resolve_url("engine/unknown")


# ---------------------------------------------------------------------------
# Successful process
# ---------------------------------------------------------------------------


class TestProcessSuccess:
    @pytest.mark.asyncio()
    async def test_basic_text_output(self):
        client = _make_client(
            [
                _ok_response(
                    {"text": "OCR result", "binary": [], "structured": None, "metadata": {}}
                ),
            ]
        )
        result = await client.process("engine/ocr", {"images": NodeOutput(text="img")}, {})
        assert result.text == "OCR result"
        await client.close()

    @pytest.mark.asyncio()
    async def test_binary_output(self):
        client = _make_client(
            [
                _ok_response(
                    {
                        "text": None,
                        "binary": [
                            {"ref": "/out/cropped.png", "mime_type": "image/png", "size_bytes": 500}
                        ],
                        "structured": None,
                        "metadata": {"region_count": 3},
                    }
                ),
            ]
        )
        result = await client.process(
            "processor/layout_detection",
            {"image": NodeOutput(text="img")},
            {},
        )
        assert result.text is None
        assert len(result.binary) == 1
        assert result.binary[0].ref == "/out/cropped.png"
        assert result.metadata == {"region_count": 3}
        await client.close()

    @pytest.mark.asyncio()
    async def test_request_body_format(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        inputs = {"image": NodeOutput(text="img"), "text": NodeOutput(text="prompt")}
        config = {"model": "qwen2-vl", "temperature": 0.7}
        await client.process("engine/model", inputs, config)

        req = client._transport.requests[0]
        import json

        body = json.loads(req.content)
        assert "inputs" in body
        assert "config" in body
        assert "image" in body["inputs"]
        assert "text" in body["inputs"]
        assert body["config"]["model"] == "qwen2-vl"
        await client.close()

    @pytest.mark.asyncio()
    async def test_base_url_override_routes_to_override(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        await client.process(
            "engine/ocr",
            {"image": NodeOutput(text="img")},
            {},
            base_url="http://easyocr.example.com",
        )

        req = client._transport.requests[0]
        assert str(req.url).startswith("http://easyocr.example.com/process")
        await client.close()

    @pytest.mark.asyncio()
    async def test_no_base_url_uses_settings_url(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        await client.process(
            "engine/ocr",
            {"image": NodeOutput(text="img")},
            {},
        )

        req = client._transport.requests[0]
        assert str(req.url).startswith("http://localhost:9001/process")
        await client.close()


# ---------------------------------------------------------------------------
# Binary ref inlining
# ---------------------------------------------------------------------------


class TestBinaryRefInlining:
    @pytest.mark.asyncio()
    async def test_local_file_ref_inlined_as_base64(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG fake image data")
            tmp_path = tmp.name

        try:
            client = _make_client(
                [
                    _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
                ]
            )
            from app.models.execution import BinaryRef

            await client.process(
                "engine/ocr",
                {"image": NodeOutput(binary=[BinaryRef(ref=tmp_path, mime_type="image/png")])},
                {},
            )

            import json

            req = client._transport.requests[0]
            body = json.loads(req.content)
            img_input = body["inputs"]["image"]
            assert img_input["text"] == base64.b64encode(b"\x89PNG fake image data").decode("ascii")
            await client.close()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio()
    async def test_nonexistent_file_ref_not_inlined(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        await client.process(
            "engine/ocr",
            {
                "image": NodeOutput(
                    binary=[BinaryRef(ref="http://example.com/img.png", mime_type="image/png")]
                )
            },
            {},
        )

        import json

        req = client._transport.requests[0]
        body = json.loads(req.content)
        img_input = body["inputs"]["image"]
        assert img_input["text"] is None
        await client.close()


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestTimeout:
    @pytest.mark.asyncio()
    async def test_timeout_raises_engine_timeout(self):
        client = _make_client(
            [
                _raise(httpx.TimeoutException("timeout")),
            ]
        )
        with pytest.raises(EngineError) as exc_info:
            await client.process("engine/ocr", {}, {})
        assert exc_info.value.error_code == ErrorCode.ENGINE_TIMEOUT
        await client.close()

    @pytest.mark.asyncio()
    async def test_provider_ssrf_error_is_sanitized(self):
        client = _make_client([_raise(SsrfBlockedError("blocked private provider 10.0.0.8"))])
        with pytest.raises(EngineError) as exc_info:
            await client.process(
                "engine/ocr",
                {},
                {},
                base_url="http://provider.example",
                provider_request=True,
            )
        assert exc_info.value.error_code == ErrorCode.ENGINE_UNREACHABLE
        assert "10.0.0.8" not in str(exc_info.value)
        await client.close()


# ---------------------------------------------------------------------------
# Retry on server errors
# ---------------------------------------------------------------------------


class TestRetry:
    @pytest.mark.asyncio()
    async def test_500_raises_invalid_response(self):
        client = _make_client(
            [
                _error_response(500, "internal error"),
            ]
        )
        with pytest.raises(EngineError) as exc_info:
            await client.process("engine/ocr", {}, {})
        assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
        assert "internal error" not in str(exc_info.value)
        # Should only have made 1 request (no retry)
        assert len(client._transport.requests) == 1
        await client.close()

    @pytest.mark.asyncio()
    async def test_429_raises_invalid_response(self):
        client = _make_client(
            [
                _error_response(429, "rate limited"),
            ]
        )
        with pytest.raises(EngineError) as exc_info:
            await client.process("engine/ocr", {}, {})
        assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
        # Should only have made 1 request (no retry)
        assert len(client._transport.requests) == 1
        await client.close()

    @pytest.mark.asyncio()
    async def test_no_retry_on_400(self):
        client = _make_client(
            [
                _error_response(400, "bad request"),
            ],
            timeout=120.0,
        )
        with pytest.raises(EngineError) as exc_info:
            await client.process("engine/ocr", {}, {})
        assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
        # Should only have made 1 request (no retry)
        assert len(client._transport.requests) == 1
        await client.close()

    @pytest.mark.asyncio()
    async def test_connect_error_raises_unreachable(self):
        client = _make_client(
            [
                _raise(httpx.ConnectError("connection refused")),
            ]
        )
        with pytest.raises(EngineError) as exc_info:
            await client.process("engine/ocr", {}, {})
        assert exc_info.value.error_code == ErrorCode.ENGINE_UNREACHABLE
        await client.close()


# ---------------------------------------------------------------------------
# make_node_executor
# ---------------------------------------------------------------------------


class TestMakeNodeExecutor:
    @pytest.mark.asyncio()
    async def test_executor_calls_process(self):
        client = _make_client(
            [
                _ok_response(
                    {"text": "via executor", "binary": [], "structured": None, "metadata": {}}
                ),
            ]
        )
        executor = make_node_executor(client)
        node = DAGNode(
            node_id="ocr-1",
            node_type="engine/ocr",
            config={"dpi": 300},
            named_inputs={},
            dependencies=set(),
        )
        inputs = {"images": NodeOutput(text="image data")}

        result = await executor(node, inputs)
        assert result.text == "via executor"

        req = client._transport.requests[0]
        import json

        body = json.loads(req.content)
        assert body["config"] == {"dpi": 300}
        assert "images" in body["inputs"]
        await client.close()

    @pytest.mark.asyncio()
    async def test_engine_service_routes_directly_with_fixed_config(self):
        client = _make_client(
            [
                _ok_response({"text": "easyocr", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        provider_store = _FakeProviderStore(
            {
                "p1": _FakeProvider(
                    id="p1",
                    provider_type="engine_service",
                    base_url="http://easyocr.example.com",
                    auth_type="none",
                    extra_config='{"fixed_config": {"language": "en"}}',
                ),
            }
        )
        executor = make_node_executor(
            client,
            auth_resolver=_FakeAuthResolver(),
            provider_resolver=lambda provider_id: provider_store.get_for_runtime(
                provider_id, "ws_test"
            ),
        )
        node = DAGNode(
            node_id="ocr-1",
            node_type="engine/ocr",
            config={"provider_id": "p1", "language": "ch"},
            named_inputs={},
            dependencies=set(),
        )

        await executor(node, {})

        req = client._transport.requests[0]
        assert str(req.url).startswith("http://easyocr.example.com/process")
        import json

        body = json.loads(req.content)
        assert body["config"] == {"language": "en"}
        await client.close()

    @pytest.mark.asyncio()
    async def test_openai_provider_always_routes_through_internal_vlm(self):
        client = _make_client(
            [
                _ok_response({"text": "vlm", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        provider_store = _FakeProviderStore(
            {
                "vlm": _FakeProvider(
                    id="vlm",
                    provider_type="openai_compatible",
                    base_url="https://api.example.com/v1",
                    auth_type="api_key",
                    api_key="top-secret",
                    api_style="openai",
                ),
            }
        )
        executor = make_node_executor(
            client,
            auth_resolver=_FakeAuthResolver(),
            provider_resolver=lambda provider_id: provider_store.get_for_runtime(
                provider_id, "ws_test"
            ),
        )
        node = DAGNode(
            node_id="vlm-1",
            node_type="engine/model",
            config={"provider_id": "vlm", "model": "vision-model"},
            named_inputs={},
            dependencies=set(),
        )

        await executor(node, {})

        req = client._transport.requests[0]
        assert str(req.url).startswith("http://localhost:9002/process")
        assert req.headers["x-docconv-credential-kind"] == "api_key"
        assert req.headers["x-docconv-credential"] == "top-secret"
        import json

        body = json.loads(req.content)
        assert body["config"]["provider_base_url"] == "https://api.example.com/v1"
        assert body["config"]["provider_api_style"] == "openai"
        assert body["config"]["provider_api_version"] is None
        assert body["config"]["model"] == "vision-model"
        assert body["config"].get("provider_id") is None
        assert b"top-secret" not in req.content
        await client.close()

    @pytest.mark.asyncio()
    async def test_engine_service_forwards_resolved_bearer_and_tls(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        provider_store = _FakeProviderStore(
            {
                "ocr-auth": _FakeProvider(
                    id="ocr-auth",
                    provider_type="engine_service",
                    base_url="http://secure-ocr.example.com",
                    auth_type="bearer_plugin",
                    bearer="bearer-secret",
                    extra_config='{"ssl_verify": false}',
                ),
            }
        )
        auth_resolver = _FakeAuthResolver()
        executor = make_node_executor(
            client,
            auth_resolver=auth_resolver,
            provider_resolver=lambda provider_id: provider_store.get_for_runtime(
                provider_id, "ws_test"
            ),
        )
        node = DAGNode(
            node_id="ocr-1",
            node_type="engine/ocr",
            config={"provider_id": "ocr-auth"},
            named_inputs={},
            dependencies=set(),
        )

        await executor(node, {})

        req = client._transport.requests[0]
        assert req.headers.get("authorization") == "Bearer bearer-secret"
        assert str(req.url).startswith("http://secure-ocr.example.com/process")
        await client.close()

    @pytest.mark.asyncio()
    async def test_azure_provider_sends_version_and_none_kind_to_vlm(self):
        client = _make_client(
            [
                _ok_response({"text": "ok", "binary": [], "structured": None, "metadata": {}}),
            ]
        )
        provider_store = _FakeProviderStore(
            {
                "azure": _FakeProvider(
                    id="azure",
                    provider_type="openai_compatible",
                    base_url="https://azure.example.com",
                    auth_type="none",
                    api_style="azure_openai",
                    api_version="2025-04-01-preview",
                ),
            }
        )
        executor = make_node_executor(
            client,
            provider_resolver=lambda provider_id: provider_store.get_for_runtime(
                provider_id, "ws_test"
            ),
        )
        node = DAGNode(
            node_id="vlm-1",
            node_type="engine/model",
            config={"provider_id": "azure", "model": "deployment-a"},
            named_inputs={},
            dependencies=set(),
        )

        await executor(node, {})

        req = client._transport.requests[0]
        assert req.headers["x-docconv-credential-kind"] == "none"
        assert "x-docconv-credential" not in req.headers
        import json

        body = json.loads(req.content)
        assert body["config"]["provider_api_style"] == "azure_openai"
        assert body["config"]["provider_api_version"] == "2025-04-01-preview"
        await client.close()


class _FakeProvider:
    def __init__(
        self,
        id,
        provider_type,
        base_url,
        auth_type="none",
        api_key=None,
        bearer=None,
        extra_config=None,
        api_style=None,
        api_version=None,
    ):
        self.id = id
        self.provider_type = provider_type
        self.base_url = base_url
        self.auth_type = auth_type
        self.api_key = api_key
        self.bearer = bearer
        self.extra_config = extra_config
        self.api_style = api_style
        self.api_version = api_version
        self.is_enabled = True


class _FakeAuthResolver:
    async def resolve(self, provider):
        if provider.api_key:
            return AuthResult(kind=CredentialKind.api_key, credential=provider.api_key)
        if provider.bearer:
            return AuthResult(kind=CredentialKind.bearer, credential=provider.bearer)
        return AuthResult()


class _FakeProviderStore:
    def __init__(self, providers: dict):
        self._providers = providers

    def get_for_runtime(self, provider_id, _workspace_id):
        return self._providers.get(provider_id)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _raise(exc: Exception) -> httpx.Response:
    """Helper that raises on transport use — _MockTransport will call this
    indirectly, but we need a different approach for exceptions."""
    # We use a special marker that our mock transport recognizes
    return _ExceptionMarker(exc)


class _ExceptionMarker:
    def __init__(self, exc: Exception):
        self.exc = exc


class _MockTransportWithExceptions(httpx.AsyncBaseTransport):
    def __init__(self, items: list):
        self._items = list(items)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._items:
            return httpx.Response(500, text="no more items")
        item = self._items.pop(0)
        if isinstance(item, _ExceptionMarker):
            raise item.exc
        return item


# Override _make_client to support exception markers
def _make_client(
    responses: list,
    timeout: float = 120.0,
) -> EngineClient:
    transport = _MockTransportWithExceptions(responses)
    client = EngineClient(settings=_FakeSettings(), timeout=timeout)
    client._client = httpx.AsyncClient(transport=transport)
    client._insecure_client = httpx.AsyncClient(transport=transport, verify=False)
    client._provider_clients[True] = httpx.AsyncClient(transport=transport)
    client._provider_clients[False] = httpx.AsyncClient(transport=transport, verify=False)
    client._transport = transport
    return client
