"""Backend tests for the internal model proxy (spec: pi-agent-runtime §internal model proxy)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from app.api.internal_proxy import (
    INTERNAL_PROXY_AUTH_HEADER,
    _ManagedStreamingResponse,
    _stream_upstream_response,
    issue_internal_proxy_grant,
)
from app.api.internal_proxy import (
    router as internal_proxy_router,
)
from app.providers.auth_registry import register_builtin_strategies
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ApiProtocol, ModelProviderCreate, ProviderType
from app.providers.store import ProviderStore
from app.services.ssrf_guard import SsrfBlockedError


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def proxy_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    register_builtin_strategies()
    app = FastAPI()
    app.include_router(internal_proxy_router)
    db_path = init_db(tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    store = ProviderStore(db_path=db_path, fernet=fernet)
    app.state.provider_store = store
    plain = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
        timeout=kwargs.get("timeout", 5.0),
        follow_redirects=False,
    )
    monkeypatch.setattr("app.api.internal_proxy.provider_ssrf_safe_client", plain)

    def _create(
        provider_type,
        protocol,
        base_url="https://api.example/v1",
        model_max_tokens=4_096,
    ):
        return store.create_provider(
            ModelProviderCreate(
                name=f"Test {protocol.value}",
                provider_type=provider_type,
                engine_category="llm",
                base_url=base_url,
                api_protocol=protocol,
                api_key="secret-token",
                auth_type="api_key",
                model_id="gpt-test",
                model_max_tokens=model_max_tokens,
                scope="workspace",  # type: ignore[arg-type]
                workspace_id="ws_proxy",
            )
        )

    app.state._create_provider = _create  # type: ignore[attr-defined]
    yield TestClient(app)


def _proxy_headers(client: TestClient, provider_id: str) -> dict[str, str]:
    token = issue_internal_proxy_grant(
        client.app,
        chatbox_session_id="chatbox-test",
        workspace_id="ws_proxy",
        provider_id=provider_id,
    )
    return {INTERNAL_PROXY_AUTH_HEADER: token}


# ---------------------------------------------------------------------------
# Per-protocol request shape and header set
# ---------------------------------------------------------------------------


@respx.mock
def test_openai_chat_completions_request_shape(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    route = respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"id": "x", "choices": []})
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        },
    )
    assert r.status_code == 200
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer secret-token"
    body = json.loads(sent.content)
    assert body["model"] == "gpt-test"
    assert body["messages"][0]["content"] == "Hi"
    assert body["stream"] is True
    assert body["store"] is False


@respx.mock
def test_openai_responses_injects_store_false(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_responses
    )
    route = respx.post("https://api.example/v1/responses").mock(
        return_value=httpx.Response(200, json={"id": "resp_1", "status": "completed"})
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_responses",
            "payload": {"input": "Hi"},
        },
    )
    assert r.status_code == 200
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer secret-token"
    body = json.loads(sent.content)
    assert body["store"] is False
    assert "previous_response_id" not in body
    assert body["model"] == "gpt-test"


@respx.mock
def test_openai_responses_strips_previous_response_id(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_responses
    )
    route = respx.post("https://api.example/v1/responses").mock(
        return_value=httpx.Response(200, json={"id": "resp_1"})
    )
    proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_responses",
            "payload": {
                "input": "Hi",
                "previous_response_id": "resp_old",
            },
        },
    )
    body = json.loads(route.calls[0].request.content)
    assert "previous_response_id" not in body


@respx.mock
def test_anthropic_messages_header_set(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api,
        ApiProtocol.anthropic_messages,
        model_max_tokens=8_192,
    )
    route = respx.post("https://api.example/v1/messages").mock(
        return_value=httpx.Response(200, json={"id": "msg_1"})
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "claude-test",
            "api_protocol": "anthropic_messages",
            "payload": {"messages": [{"role": "user", "content": "Hi"}]},
        },
    )
    assert r.status_code == 200
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "secret-token"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in sent.headers
    body = json.loads(sent.content)
    assert body["max_tokens"] == 8_192
    assert body["model"] == "claude-test"


# ---------------------------------------------------------------------------
# Credential never logged or persisted beyond invocation
# ---------------------------------------------------------------------------


@respx.mock
def test_credential_not_in_response_body(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"id": "x", "choices": []})
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {"messages": [{"role": "user", "content": "Hi"}]},
        },
    )
    assert b"secret-token" not in r.content


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_proxy_rejects_missing_internal_grant(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    response = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {},
        },
    )
    assert response.status_code == 401


def test_proxy_rejects_grant_for_another_provider(proxy_client: TestClient) -> None:
    first = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    second = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    response = proxy_client.post(
        f"/internal/proxy/invoke/{second.id}",
        headers=_proxy_headers(proxy_client, first.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {},
        },
    )
    assert response.status_code == 401


def test_proxy_rejects_non_llm_api(proxy_client: TestClient) -> None:
    store: ProviderStore = proxy_client.app.state.provider_store
    row = store.create_provider(
        ModelProviderCreate(
            name="OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8080",
            scope="workspace",  # type: ignore[arg-type]
            workspace_id="ws_proxy",
        )
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "x",
            "api_protocol": "openai_chat_completions",
            "payload": {},
        },
    )
    assert r.status_code == 400


def test_proxy_rejects_protocol_mismatch(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "anthropic_messages",
            "payload": {},
        },
    )
    assert r.status_code == 400


def test_proxy_not_found(proxy_client: TestClient) -> None:
    r = proxy_client.post(
        "/internal/proxy/invoke/bad-id",
        headers=_proxy_headers(proxy_client, "bad-id"),
        json={
            "model_id": "x",
            "api_protocol": "openai_chat_completions",
            "payload": {},
        },
    )
    assert r.status_code == 404


def test_proxy_rejects_missing_fields(proxy_client: TestClient) -> None:
    r = proxy_client.post(
        "/internal/proxy/invoke/any",
        headers=_proxy_headers(proxy_client, "any"),
        json={"payload": {}},
    )
    assert r.status_code == 400


@pytest.mark.parametrize("model_id", [{"id": "gpt-test"}, ["gpt-test"], 7, "", "   "])
def test_proxy_rejects_non_string_or_blank_model_id(
    proxy_client: TestClient,
    model_id: object,
) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )

    response = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": model_id,
            "api_protocol": "openai_chat_completions",
            "payload": {},
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "model_id must be a non-empty string"}


@pytest.mark.parametrize("serialized_body", ["[]", '"request"', "1", "null"])
def test_proxy_rejects_non_object_request_body(
    proxy_client: TestClient,
    serialized_body: str,
) -> None:
    response = proxy_client.post(
        "/internal/proxy/invoke/any",
        headers={
            **_proxy_headers(proxy_client, "any"),
            "Content-Type": "application/json",
        },
        content=serialized_body,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Request body must be a JSON object"}


@pytest.mark.parametrize("payload", [[], "messages", 1, None])
def test_proxy_rejects_non_object_payload(
    proxy_client: TestClient,
    payload: object,
) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )

    response = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": payload,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "payload must be a JSON object"}


@respx.mock
def test_proxy_upstream_error_returns_502(proxy_client: TestClient) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    respx.post("https://api.example/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    r = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {"messages": []},
        },
    )
    assert r.status_code == 502


def test_proxy_ssrf_blocked_returns_403(
    proxy_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )

    async def blocked(_request: httpx.Request) -> httpx.Response:
        raise SsrfBlockedError("blocked")

    monkeypatch.setattr(
        "app.api.internal_proxy.provider_ssrf_safe_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(blocked)),
    )

    response = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {"messages": []},
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Provider endpoint blocked by network policy"}


def test_proxy_streams_bytes_and_closes_upstream_resources(
    proxy_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = proxy_client.app.state._create_provider(  # type: ignore[attr-defined]
        ProviderType.llm_api, ApiProtocol.openai_chat_completions
    )
    stream = _TrackingStream(b"data: first\n\n", b"data: [DONE]\n\n")
    clients: list[httpx.AsyncClient] = []

    async def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    def client_factory(**_kwargs: object) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        clients.append(client)
        return client

    monkeypatch.setattr(
        "app.api.internal_proxy.provider_ssrf_safe_client",
        client_factory,
    )

    response = proxy_client.post(
        f"/internal/proxy/invoke/{row.id}",
        headers=_proxy_headers(proxy_client, row.id),
        json={
            "model_id": "gpt-test",
            "api_protocol": "openai_chat_completions",
            "payload": {"messages": [], "stream": True},
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"
    assert response.content == b"data: first\n\ndata: [DONE]\n\n"
    assert stream.closed is True
    assert len(clients) == 1
    assert clients[0].is_closed is True


@pytest.mark.asyncio
async def test_proxy_closes_upstream_when_downstream_stops_early() -> None:
    stream = _TrackingStream(b"first", b"second")
    upstream = httpx.Response(200, stream=stream)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: upstream))
    body = _stream_upstream_response(upstream, client)

    assert await anext(body) == b"first"
    await body.aclose()

    assert stream.closed is True
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_proxy_closes_upstream_before_downstream_reads_first_byte() -> None:
    stream = _TrackingStream(b"first")
    upstream = httpx.Response(200, stream=stream)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: upstream))
    body = _stream_upstream_response(upstream, client)

    await body.aclose()
    await body.aclose()

    assert stream.closed is True
    assert client.is_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at_send", [1, 2, 3, None])
async def test_managed_streaming_response_closes_on_every_asgi_exit(
    fail_at_send: int | None,
) -> None:
    stream = _TrackingStream(b"first")
    upstream = httpx.Response(200, stream=stream)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: upstream))
    body = _stream_upstream_response(upstream, client)
    response = _ManagedStreamingResponse(
        body,
        status_code=200,
        headers={"content-type": "application/octet-stream"},
    )
    send_count = 0

    async def receive() -> dict[str, str]:
        return {"type": "http.disconnect"}

    async def send(_message: object) -> None:
        nonlocal send_count
        send_count += 1
        if send_count == fail_at_send:
            raise OSError("downstream closed")

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    if fail_at_send is None:
        await response(scope, receive, send)  # type: ignore[arg-type]
    else:
        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)  # type: ignore[arg-type]

    assert stream.closed is True
    assert client.is_closed is True
