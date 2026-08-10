from __future__ import annotations

import httpx
import pytest

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.services.sandbox_client import SandboxClient
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits


class _QueueTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "http://test"))


@pytest.mark.asyncio()
async def test_process_parses_strict_response() -> None:
    transport = _QueueTransport(
        [
            _response(
                200,
                {
                    "request_id": "req-1",
                    "status": "ok",
                    "result": {
                        "text": "ok",
                        "binary": [],
                        "structured": {"done": True},
                        "metadata": {},
                    },
                    "error": None,
                    "metrics": {"wall_time_ms": 12},
                },
            )
        ]
    )
    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )

    response = await client.process(
        request_id="req-1",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )

    assert response.text == "ok"
    assert transport.requests[0].url.path == "/process"
    await client.close()


@pytest.mark.asyncio()
async def test_process_maps_timeout_and_unreachable_errors() -> None:
    timeout_client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=_QueueTransport([httpx.TimeoutException("timeout")])),
    )
    with pytest.raises(EngineError) as timeout_exc:
        await timeout_client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert timeout_exc.value.error_code == ErrorCode.ENGINE_TIMEOUT
    await timeout_client.close()

    unreachable_client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=_QueueTransport([httpx.ConnectError("refused")])),
    )
    with pytest.raises(EngineError) as unreachable_exc:
        await unreachable_client.health()
    assert unreachable_exc.value.error_code == ErrorCode.ENGINE_UNREACHABLE
    await unreachable_client.close()


@pytest.mark.asyncio()
async def test_process_maps_non_200_and_invalid_payload_without_leaking_content() -> None:
    invalid_client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport(
                [_response(422, {"detail": "user code and /tmp/path should not leak"})]
            )
        ),
    )
    with pytest.raises(EngineError) as invalid_exc:
        await invalid_client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert invalid_exc.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert "/tmp/path" not in str(invalid_exc.value)
    await invalid_client.close()

    malformed_client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport(
                [
                    _response(
                        200,
                        {
                            "request_id": "req-1",
                            "status": "ok",
                            "result": {},
                            "metrics": {},
                        },
                    )
                ]
            )
        ),
    )
    with pytest.raises(EngineError) as malformed_exc:
        await malformed_client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert malformed_exc.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
    await malformed_client.close()


@pytest.mark.asyncio()
async def test_process_maps_queue_full_to_engine_rate_limited() -> None:
    queue_full_client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport(
                [
                    _response(
                        503,
                        {
                            "request_id": "req-1",
                            "status": "error",
                            "result": None,
                            "error": {"kind": "queue_full", "message": "busy"},
                            "metrics": {},
                        },
                    )
                ]
            )
        ),
    )

    with pytest.raises(EngineError) as queue_full_exc:
        await queue_full_client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert queue_full_exc.value.error_code == ErrorCode.ENGINE_RATE_LIMITED
    await queue_full_client.close()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("kind", "status_code", "expected_code"),
    [
        ("timeout", 504, ErrorCode.ENGINE_TIMEOUT),
        ("queue_full", 503, ErrorCode.ENGINE_RATE_LIMITED),
        ("unavailable", 503, ErrorCode.ENGINE_UNREACHABLE),
        ("protocol", 502, ErrorCode.ENGINE_INVALID_RESPONSE),
        ("internal", 502, ErrorCode.ENGINE_INVALID_RESPONSE),
        ("invalid", 422, ErrorCode.INVALID_NODE_CONFIG),
        ("code", 422, ErrorCode.INVALID_NODE_CONFIG),
        ("runtime", 422, ErrorCode.INVALID_NODE_CONFIG),
        ("resource", 422, ErrorCode.INVALID_NODE_CONFIG),
    ],
)
async def test_process_maps_safe_error_kinds_and_retains_kind_detail(
    kind: str, status_code: int, expected_code: ErrorCode
) -> None:
    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport(
                [
                    _response(
                        status_code,
                        {
                            "request_id": "req-1",
                            "status": "error",
                            "result": None,
                            "error": {"kind": kind, "message": "safe"},
                            "metrics": {},
                        },
                    )
                ]
            )
        ),
    )

    with pytest.raises(EngineError) as exc_info:
        await client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert exc_info.value.error_code == expected_code
    assert exc_info.value.details is not None
    assert exc_info.value.details["sandbox_kind"] == kind
    await client.close()


@pytest.mark.asyncio()
async def test_process_malformed_error_envelope_falls_back_to_invalid_response() -> None:
    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport([_response(503, {"detail": "bad envelope"})])
        ),
    )

    with pytest.raises(EngineError) as exc_info:
        await client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
    await client.close()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("kind", "status_code", "expected_code"),
    [
        ("protocol", 422, ErrorCode.ENGINE_INVALID_RESPONSE),
        ("internal", 422, ErrorCode.ENGINE_INVALID_RESPONSE),
        ("invalid", 502, ErrorCode.INVALID_NODE_CONFIG),
        ("code", 502, ErrorCode.INVALID_NODE_CONFIG),
        ("runtime", 502, ErrorCode.INVALID_NODE_CONFIG),
        ("resource", 502, ErrorCode.INVALID_NODE_CONFIG),
        ("timeout", 422, ErrorCode.ENGINE_TIMEOUT),
        ("queue_full", 422, ErrorCode.ENGINE_RATE_LIMITED),
        ("unavailable", 422, ErrorCode.ENGINE_UNREACHABLE),
    ],
)
async def test_process_prefers_recognized_safe_kind_over_http_status(
    kind: str, status_code: int, expected_code: ErrorCode
) -> None:
    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(
            transport=_QueueTransport(
                [
                    _response(
                        status_code,
                        {
                            "request_id": "req-1",
                            "status": "error",
                            "result": None,
                            "error": {"kind": kind, "message": "safe"},
                            "metrics": {},
                        },
                    )
                ]
            )
        ),
    )

    with pytest.raises(EngineError) as exc_info:
        await client.process(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
    assert exc_info.value.error_code == expected_code
    assert exc_info.value.details is not None
    assert exc_info.value.details["sandbox_kind"] == kind
    await client.close()


@pytest.mark.asyncio()
async def test_health_and_config_only_accept_expected_shape() -> None:
    transport = _QueueTransport(
        [
            _response(200, {"status": "ok", "version": "1.0", "runner_reachable": True}),
            _response(
                200,
                {
                    "engine": "adaptor-sandbox",
                    "version": "1.0",
                    "schema_version": "v1",
                    "policy_digest": POLICY_DIGEST,
                    "limits": {"max_code_bytes": 65536},
                    "network_policy": "runner-network-none",
                },
            ),
        ]
    )
    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )

    health = await client.health()
    config = await client.config()

    assert health["runner_reachable"] is True
    assert config["policy_digest"] == POLICY_DIGEST
    assert transport.requests[0].url.path == "/health"
    assert transport.requests[1].url.path == "/config"
    await client.close()
