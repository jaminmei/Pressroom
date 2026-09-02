"""Backend tests for the llm_api readiness probe (spec: model-readiness-test)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.providers.readiness as readiness_module
from app.api.auth import get_authenticated_context
from app.api.providers import router as providers_router
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.providers.auth import AuthResult, CredentialKind
from app.providers.auth_registry import register_builtin_strategies
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ApiProtocol, ModelProviderCreate, ProviderScope, ProviderType
from app.providers.readiness import (
    READINESS_TOOL_NAME,
    _is_terminal_stream_payload,
    run_readiness_probe,
)
from app.providers.store import ProviderStore


@pytest.fixture
def provider_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def plain_client(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=kwargs.get("timeout", 5.0),
            follow_redirects=False,
        )

    monkeypatch.setattr("app.providers.readiness.provider_ssrf_safe_client", plain_client)
    store = ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    row = store.create_provider(
        ModelProviderCreate(
            name="Chat",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="gpt-test",
            scope="workspace",  # type: ignore[arg-type]
            workspace_id="ws-1",
        )
    )
    return store, row


def _auth() -> AuthResult:
    return AuthResult(kind=CredentialKind.api_key, credential="secret")


def _chat_text_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chat-text",
            "choices": [
                {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
            ],
        },
    )


def _chat_tool_response(call_id: str = "provider-call-ready") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chat-tool",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_opaque": "provider-context",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": READINESS_TOOL_NAME, "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    )


def _chat_stream_response(*, terminal: bool = True) -> httpx.Response:
    content = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'
    if terminal:
        content += b"data: [DONE]\n\n"
    return httpx.Response(200, content=content)


class _CancellationStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'

    async def aclose(self) -> None:
        self.closed = True


def _chat_success_handler():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request, route):
        requests.append(request)
        call_number = len(requests)
        if call_number in {2, 6}:
            return _chat_stream_response()
        if call_number == 3:
            return _chat_tool_response()
        return _chat_text_response()

    return handler, requests


def _responses_text_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp-text",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "OK"}],
                }
            ],
        },
    )


def _responses_tool_response(call_id: str = "provider-response-call") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp-tool",
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "reasoning-1", "encrypted_content": "opaque"},
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": READINESS_TOOL_NAME,
                    "arguments": "{}",
                },
            ],
        },
    )


def _responses_stream_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=(
            b"event: response.output_text.delta\n"
            b'data: {"type":"response.output_text.delta","delta":"OK"}\n\n'
            b'event: response.completed\ndata: {"type":"response.completed"}\n\n'
        ),
    )


def _anthropic_text_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg-text",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
        },
    )


def _anthropic_tool_response(call_id: str = "provider-tool-use") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg-tool",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "opaque-provider-context"},
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": READINESS_TOOL_NAME,
                    "input": {},
                },
            ],
            "stop_reason": "tool_use",
        },
    )


def _anthropic_stream_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=(
            b"event: content_block_delta\n"
            b'data: {"type":"content_block_delta",'
            b'"delta":{"type":"text_delta","text":"OK"}}\n\n'
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        ),
    )


@pytest.mark.parametrize(
    ("protocol", "payload", "expected"),
    [
        (ApiProtocol.openai_chat_completions, "[DONE]", True),
        (ApiProtocol.openai_responses, '{"type":"response.completed"}', True),
        (ApiProtocol.anthropic_messages, '{"type":"message_stop"}', True),
        (
            ApiProtocol.openai_responses,
            '{"type":"response.output_text.delta","delta":"response.completed"}',
            False,
        ),
        (
            ApiProtocol.anthropic_messages,
            '{"type":"content_block_delta","text":"message_stop"}',
            False,
        ),
        (ApiProtocol.anthropic_messages, "event: message_stop", False),
    ],
)
def test_terminal_stream_payload_requires_exact_protocol_event(
    protocol: ApiProtocol,
    payload: str,
    expected: bool,
) -> None:
    assert _is_terminal_stream_payload(protocol, payload) is expected


@pytest.mark.asyncio
async def test_missing_non_none_credential_returns_sanitized_failure(provider_row) -> None:
    _, row = provider_row
    malformed_auth = object.__new__(AuthResult)
    object.__setattr__(malformed_auth, "kind", CredentialKind.api_key)
    object.__setattr__(malformed_auth, "credential", None)

    result = await run_readiness_probe(row, malformed_auth)

    assert result.chatbot_ready is False
    assert [(step.name, step.status, step.detail) for step in result.steps] == [
        ("non_streaming_text", "fail", "Provider credential is missing")
    ]


# ---------------------------------------------------------------------------
# Step 1: non-streaming text
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_probe_enforces_an_overall_timeout(provider_row) -> None:
    _, row = provider_row

    async def never_respond(_request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=never_respond)

    result = await run_readiness_probe(
        row,
        _auth(),
        timeout=30.0,
        overall_timeout=0.01,
    )

    assert result.chatbot_ready is False
    assert [(step.name, step.status, step.detail) for step in result.steps] == [
        (
            "non_streaming_text",
            "fail",
            "Readiness probe exceeded its overall timeout",
        )
    ]


@respx.mock
@pytest.mark.asyncio
async def test_non_streaming_failure_fails_readiness(provider_row) -> None:
    _, row = provider_row
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    result = await run_readiness_probe(row, _auth())
    assert result.chatbot_ready is False
    assert result.steps[0].status == "fail"
    assert result.steps[0].name == "non_streaming_text"
    assert "boom" not in (result.steps[0].detail or "")
    assert "HTTP 500" in (result.steps[0].detail or "")


@respx.mock
@pytest.mark.asyncio
async def test_http_200_without_assistant_text_fails_readiness(provider_row) -> None:
    _, row = provider_row
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is False
    assert [(step.name, step.status) for step in result.steps] == [("non_streaming_text", "fail")]
    assert "assistant text" in (result.steps[0].detail or "")


# ---------------------------------------------------------------------------
# Step 2: streaming text termination
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_streaming_termination_failure_fails_readiness(provider_row) -> None:
    _, row = provider_row
    call_count = 0

    def handler(_request, route):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return httpx.Response(
                200,
                content=(
                    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                    b'data: {"choices":[{"delta":{"content":"there"}}]}\n\n'
                ),
            )
        return _chat_text_response()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    streaming_step = next(s for s in result.steps if s.name == "streaming_text")
    assert streaming_step.status == "fail"
    assert "terminal" in (streaming_step.detail or "").lower()
    assert result.chatbot_ready is False


@respx.mock
@pytest.mark.asyncio
async def test_streaming_terminates_correctly_passes_step2(provider_row) -> None:
    _, row = provider_row
    handler, _requests = _chat_success_handler()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    assert result.steps[1].name == "streaming_text"
    assert result.steps[1].status == "pass"
    assert result.chatbot_ready is True


# ---------------------------------------------------------------------------
# Step 3+4: tool round-trip
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tool_call_failure_fails_readiness(provider_row) -> None:
    _, row = provider_row

    call_count = {"n": 0}

    def handler(request, route):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _chat_text_response()
        if call_count["n"] == 2:
            return _chat_stream_response()
        return httpx.Response(500, json={"error": "tool rejected"})

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    tool_step = next((s for s in result.steps if s.name == "tool_call"), None)
    assert tool_step is not None
    assert tool_step.status == "fail"
    assert result.chatbot_ready is False


@respx.mock
@pytest.mark.asyncio
async def test_http_200_without_forced_tool_call_fails_step3(provider_row) -> None:
    _, row = provider_row
    call_count = 0

    def handler(request, route):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _chat_text_response()
        if call_count == 2:
            return _chat_stream_response()
        return httpx.Response(200, json={})

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is False
    assert result.steps[-1].name == "tool_call"
    assert result.steps[-1].status == "fail"


@respx.mock
@pytest.mark.asyncio
async def test_tool_result_replays_provider_call_context_and_requires_final_text(
    provider_row,
) -> None:
    _, row = provider_row
    requests: list[httpx.Request] = []

    def handler(request, route):
        requests.append(request)
        call_number = len(requests)
        if call_number == 1:
            return _chat_text_response()
        if call_number == 2:
            return _chat_stream_response()
        if call_number == 3:
            return _chat_tool_response(call_id="provider-call-42")
        return httpx.Response(200, json={})

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is False
    assert result.steps[-1].name == "tool_result"
    assert result.steps[-1].status == "fail"
    submitted = json.loads(requests[3].content)
    assert submitted["messages"][1]["reasoning_opaque"] == "provider-context"
    assert submitted["messages"][1]["tool_calls"][0]["id"] == "provider-call-42"
    assert submitted["messages"][2]["tool_call_id"] == "provider-call-42"


@respx.mock
@pytest.mark.asyncio
async def test_responses_replays_reasoning_and_provider_call_id(provider_row) -> None:
    _, chat_row = provider_row
    row = chat_row.model_copy(update={"api_protocol": ApiProtocol.openai_responses})
    requests: list[httpx.Request] = []

    def handler(request, route):
        requests.append(request)
        call_number = len(requests)
        if call_number in {2, 6}:
            return _responses_stream_response()
        if call_number == 3:
            return _responses_tool_response(call_id="responses-call-42")
        return _responses_text_response()

    respx.post("https://api.example/v1/responses").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is True
    submitted = json.loads(requests[3].content)
    assert submitted["input"][1]["type"] == "reasoning"
    assert submitted["input"][1]["encrypted_content"] == "opaque"
    assert submitted["input"][2]["call_id"] == "responses-call-42"
    assert submitted["input"][3]["call_id"] == "responses-call-42"


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_replays_thinking_and_provider_tool_use_id(provider_row) -> None:
    _, chat_row = provider_row
    row = chat_row.model_copy(update={"api_protocol": ApiProtocol.anthropic_messages})
    requests: list[httpx.Request] = []

    def handler(request, route):
        requests.append(request)
        call_number = len(requests)
        if call_number in {2, 5}:
            return _anthropic_stream_response()
        if call_number == 3:
            return _anthropic_tool_response(call_id="anthropic-call-42")
        return _anthropic_text_response()

    respx.post("https://api.example/v1/messages").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is True
    assert result.steps[4].name == "store_false"
    assert result.steps[4].status == "skipped"
    submitted = json.loads(requests[3].content)
    assert submitted["messages"][1]["content"][0]["type"] == "thinking"
    assert submitted["messages"][1]["content"][1]["id"] == "anthropic-call-42"
    assert submitted["messages"][2]["content"][0]["tool_use_id"] == "anthropic-call-42"


# ---------------------------------------------------------------------------
# Step 5: store:false (openai_responses only)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_store_false_rejection_fails_readiness_for_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def plain_client(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=kwargs.get("timeout", 5.0),
            follow_redirects=False,
        )

    monkeypatch.setattr("app.providers.readiness.provider_ssrf_safe_client", plain_client)
    store = ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    row = store.create_provider(
        ModelProviderCreate(
            name="Responses",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_responses,
            api_key="secret",
            model_id="gpt-test",
            scope="workspace",  # type: ignore[arg-type]
            workspace_id="ws-1",
        )
    )

    call_count = {"n": 0}

    def handler(request, route):
        call_count["n"] += 1
        if call_count["n"] == 2:
            return _responses_stream_response()
        if call_count["n"] == 3:
            return _responses_tool_response()
        if call_count["n"] == 5:
            return httpx.Response(400, json={"error": {"message": "store not supported"}})
        return _responses_text_response()

    respx.post("https://api.example/v1/responses").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    store_false_step = next((s for s in result.steps if s.name == "store_false"), None)
    assert store_false_step is not None
    assert store_false_step.status == "fail"
    assert result.chatbot_ready is False


@respx.mock
@pytest.mark.asyncio
async def test_store_false_is_required_for_chat_completions(provider_row) -> None:
    _, row = provider_row
    handler, requests = _chat_success_handler()
    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    store_false_step = next((s for s in result.steps if s.name == "store_false"), None)
    assert store_false_step is not None
    assert store_false_step.status == "pass"
    assert json.loads(requests[4].content)["store"] is False


# ---------------------------------------------------------------------------
# Full success path (openai_chat_completions)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_full_success_path_chat_completions(provider_row) -> None:
    _, row = provider_row
    handler, _requests = _chat_success_handler()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)
    result = await run_readiness_probe(row, _auth())
    assert result.chatbot_ready is True
    step_names = [s.name for s in result.steps]
    assert step_names == [
        "non_streaming_text",
        "streaming_text",
        "tool_call",
        "tool_result",
        "store_false",
        "cancellation_settle",
    ]
    assert all(step.status == "pass" for step in result.steps)


@respx.mock
@pytest.mark.asyncio
async def test_cancellation_without_stream_data_fails_readiness(provider_row) -> None:
    _, row = provider_row
    call_count = 0

    def handler(request, route):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return _chat_stream_response()
        if call_count == 3:
            return _chat_tool_response()
        if call_count == 6:
            return httpx.Response(200, content=b"data: [DONE]\n\n")
        return _chat_text_response()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is False
    assert result.steps[-1].name == "cancellation_settle"
    assert result.steps[-1].status == "fail"


@respx.mock
@pytest.mark.asyncio
async def test_cancellation_closes_provider_stream_after_first_data_event(provider_row) -> None:
    _, row = provider_row
    call_count = 0
    cancellation_stream = _CancellationStream()

    def handler(request, route):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return _chat_stream_response()
        if call_count == 3:
            return _chat_tool_response()
        if call_count == 6:
            return httpx.Response(200, stream=cancellation_stream)
        return _chat_text_response()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)

    result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is True
    assert cancellation_stream.closed is True
    assert result.steps[-1].detail == (
        "Provider stream cancellation completed; Pi settlement is integration-tested separately"
    )


# ---------------------------------------------------------------------------
# Sanitization: upstream body never in detail
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_upstream_body_never_in_failure_detail(provider_row) -> None:
    _, row = provider_row
    secret_body = "SUPER_SECRET_API_KEY_LEAK_xyz123"
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": secret_body}})
    )
    result = await run_readiness_probe(row, _auth())
    for step in result.steps:
        assert secret_body not in (step.detail or "")
    assert result.chatbot_ready is False


@respx.mock
@pytest.mark.asyncio
async def test_internal_probe_failure_is_logged_without_sensitive_details(
    provider_row,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, row = provider_row
    sensitive_detail = "SENSITIVE_INTERNAL_DIAGNOSTIC"

    def fail_validation(_protocol: ApiProtocol, _response: httpx.Response) -> None:
        raise KeyError(sensitive_detail)

    monkeypatch.setattr(readiness_module, "_require_assistant_text", fail_validation)
    respx.post("https://api.example/v1/chat/completions").mock(return_value=_chat_text_response())

    with caplog.at_level("ERROR", logger="app.providers.readiness"):
        result = await run_readiness_probe(row, _auth())

    assert result.chatbot_ready is False
    assert result.steps[0].detail == "Readiness probe failed internally (KeyError)"
    assert "Unexpected readiness probe failure error_type=KeyError" in caplog.text
    assert "Traceback" not in caplog.text
    assert sensitive_detail not in caplog.text


# ---------------------------------------------------------------------------
# Integration: POST /api/providers/{id}/readiness-test
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    register_builtin_strategies()
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workspace.db'}")
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(UserAccount(id="usr_r", email="r@example.com", password_hash="x", name=None))
        session.add(
            Workspace(id="ws_r", name="R", slug=None, description=None, owner_user_id="usr_r")
        )
        session.add(WorkspaceMember(id="wsm_r", workspace_id="ws_r", user_id="usr_r", role="owner"))
        session.commit()
    app = FastAPI()
    app.include_router(providers_router, prefix="/api")
    app.dependency_overrides[get_authenticated_context] = lambda: AuthenticatedContext(
        user=AuthUser(id="usr_r", email="r@example.com"),
        session=AuthSessionInfo(
            id="as_r",
            user_id="usr_r",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id="ws_r",
    )
    db_path = init_db(tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    app.state.provider_store = ProviderStore(db_path=db_path, fernet=fernet)
    plain_client_factory = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
        timeout=kwargs.get("timeout", 5.0),
        follow_redirects=False,
    )
    monkeypatch.setattr("app.providers.readiness.provider_ssrf_safe_client", plain_client_factory)
    yield TestClient(app)


@respx.mock
def test_readiness_endpoint_persists_chatbot_ready(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/providers",
        json={
            "name": "Chat",
            "provider_type": "llm_api",
            "engine_category": "llm",
            "base_url": "https://api.example/v1",
            "api_protocol": "openai_chat_completions",
            "api_key": "secret",
            "model_id": "gpt-test",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]

    handler, _requests = _chat_success_handler()

    respx.post("https://api.example/v1/chat/completions").mock(side_effect=handler)

    r = api_client.post(f"/api/providers/{provider_id}/readiness-test")
    assert r.status_code == 200
    data = r.json()
    assert data["chatbot_ready"] is True
    assert len(data["steps"]) == 6

    detail = api_client.get(f"/api/providers/{provider_id}").json()
    assert detail["chatbot_ready"] is True


def test_readiness_step_status_is_constrained_in_openapi(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()

    status_schema = schema["components"]["schemas"]["ReadinessStepResult"]["properties"]["status"]
    assert status_schema["enum"] == ["pass", "fail", "skipped"]


def test_readiness_endpoint_rejects_non_llm_api(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/providers",
        json={
            "name": "OCR",
            "provider_type": "engine_service",
            "engine_category": "ocr",
            "base_url": "http://ocr:8080",
        },
    )
    provider_id = created.json()["id"]
    r = api_client.post(f"/api/providers/{provider_id}/readiness-test")
    assert r.status_code == 400


def test_readiness_endpoint_rejects_system_provider(api_client: TestClient) -> None:
    store: ProviderStore = api_client.app.state.provider_store
    provider = store.create_provider(
        ModelProviderCreate(
            name="System chat",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="gpt-test",
            scope=ProviderScope.system,
        )
    )

    response = api_client.post(f"/api/providers/{provider.id}/readiness-test")

    assert response.status_code == 409
    assert response.json()["detail"] == "System providers are read-only"
    assert store.get_provider(provider.id).chatbot_ready is False  # type: ignore[union-attr]


def test_readiness_endpoint_not_found(api_client: TestClient) -> None:
    r = api_client.post("/api/providers/bad-id/readiness-test")
    assert r.status_code == 404
