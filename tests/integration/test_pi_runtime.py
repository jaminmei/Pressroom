"""Integration tests for the Node Pi runtime launcher (tasks 4.1-4.6).

Boots the real Node child (pi_runtime/src/main.mjs) against the FastAPI app
with the internal model proxy mounted and a mocked upstream at the HTTP
transport layer (respx), reusing the pattern from tests/unit/test_internal_proxy.py.

The mocked upstream speaks OpenAI Chat Completions SSE, which is what the
pinned Pi SDK's openai-completions implementation consumes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.api.internal_proxy import issue_internal_proxy_grant
from app.api.internal_proxy import router as internal_proxy_router
from app.providers.auth_registry import register_builtin_strategies
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import (
    ApiProtocol,
    ModelProviderCreate,
    ProviderScope,
    ProviderType,
)
from app.providers.store import ProviderStore
from app.services.pi_runtime import PiRuntimeError, PiRuntimeHandle, PiRuntimeLauncher

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_NODE_MODULES = REPO_ROOT / "pi_runtime" / "node_modules" / "@earendil-works"
NODE_BIN = os.environ.get("PI_NODE_BIN", "node")

pytestmark = pytest.mark.skipif(
    os.environ.get("PI_RUNTIME_SKIP") not in (None, "", "0", "false")
    or not RUNTIME_NODE_MODULES.is_dir()
    or shutil.which(NODE_BIN) is None,
    reason="PI_RUNTIME_SKIP set, or pi_runtime dependencies / node binary unavailable",
)

UPSTREAM_BASE = "https://api.example/v1"
PROMPT_TEXT = "Say hello in exactly one short sentence."


def _sse_body(*chunks: dict[str, Any]) -> bytes:
    lines = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return (lines + "data: [DONE]\n\n").encode("utf-8")


def _streaming_upstream_response() -> httpx.Response:
    chunk_base = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-test",
    }
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream"},
        content=_sse_body(
            {
                **chunk_base,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                **chunk_base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "Hello from the mocked upstream."},
                        "finish_reason": None,
                    }
                ],
            },
            {**chunk_base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {
                **chunk_base,
                "choices": [],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
            },
        ),
    )


class _ProxyServer:
    """Serves the internal proxy app on an ephemeral port in a daemon thread."""

    def __init__(self, app: FastAPI) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> str:
        self._thread.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self._server.started and self._server.servers:
                port = self._server.servers[0].sockets[0].getsockname()[1]
                return f"http://127.0.0.1:{port}"
            time.sleep(0.05)
        raise RuntimeError("internal proxy server failed to start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise RuntimeError("internal proxy server failed to stop")


@pytest.fixture
def runtime_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workspace.db'}")

    register_builtin_strategies()
    app = FastAPI()
    app.include_router(internal_proxy_router)

    db_path = init_db(tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    store = ProviderStore(db_path=db_path, fernet=fernet)
    app.state.provider_store = store
    provider = store.create_provider(
        ModelProviderCreate(
            name="Pi test provider",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url=UPSTREAM_BASE,
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret-token",
            auth_type="api_key",
            model_id="gpt-test",
            scope=ProviderScope.workspace,
            workspace_id="ws_pi",
        )
    )
    proxy_token = issue_internal_proxy_grant(
        app,
        chatbox_session_id="chatbox-pi-test",
        workspace_id="ws_pi",
        provider_id=provider.id,
    )

    plain_client = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
        timeout=kwargs.get("timeout", 5.0),
        follow_redirects=False,
    )
    monkeypatch.setattr("app.api.internal_proxy.provider_ssrf_safe_client", plain_client)

    server = _ProxyServer(app)
    proxy_base = server.start()
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    try:
        yield {
            "provider_id": provider.id,
            "proxy_url": f"{proxy_base}/internal/proxy/invoke/{provider.id}",
            "proxy_token": proxy_token,
            "workspace_root": workspace_root,
        }
    finally:
        server.stop()


async def _drive_session(
    runtime_env: dict[str, Any],
    on_started: Callable[[PiRuntimeHandle], Awaitable[None]],
    stop_predicate: Callable[[dict[str, Any]], bool],
    on_event: Callable[[PiRuntimeHandle, dict[str, Any]], Awaitable[None]] | None = None,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Run one session end to end on a single event loop and return its events."""
    launcher = PiRuntimeLauncher()
    handle = await launcher.start_session(
        provider_id=str(runtime_env["provider_id"]),
        model_id="gpt-test",
        model_context_window=200_000,
        model_max_tokens=8_192,
        model_reasoning=True,
        api_protocol="openai_chat_completions",
        proxy_url=str(runtime_env["proxy_url"]),
        proxy_token=str(runtime_env["proxy_token"]),
        workspace_root=Path(runtime_env["workspace_root"]),
    )
    await on_started(handle)
    collected: list[dict[str, Any]] = []
    events = handle.events()
    try:
        async with asyncio.timeout(timeout):
            async for event in events:
                collected.append(event)
                if on_event is not None:
                    await on_event(handle, event)
                if stop_predicate(event):
                    return collected
        raise AssertionError("event stream ended before the expected terminal event")
    finally:
        await events.aclose()
        await handle.stop()


def _user_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


@respx.mock
def test_runtime_streams_exchange_through_proxy_and_settles(
    runtime_env: dict[str, Any],
) -> None:
    route = respx.post(f"{UPSTREAM_BASE}/chat/completions").mock(
        return_value=_streaming_upstream_response()
    )

    async def on_started(handle: PiRuntimeHandle) -> None:
        await handle.send_command({"id": "req-1", "type": "prompt", "message": PROMPT_TEXT})

    events = asyncio.run(
        _drive_session(runtime_env, on_started, lambda event: event.get("type") == "agent_settled")
    )

    assert route.called
    upstream_request = route.calls[0].request
    assert upstream_request.headers["authorization"] == "Bearer secret-token"
    forwarded = json.loads(upstream_request.content)
    assert forwarded["model"] == "gpt-test"
    assert forwarded["stream"] is True
    assert any(
        message.get("role") == "user" and _user_text(message) == PROMPT_TEXT
        for message in forwarded["messages"]
    )

    event_names = {event.get("type") for event in events}
    assert "message_start" in event_names
    assert "message_end" in event_names
    assert "agent_settled" in event_names
    assert any(
        event.get("type") == "message_update"
        and event.get("assistantMessageEvent", {}).get("type") == "text_delta"
        for event in events
    )
    assert any(
        event.get("type") == "response" and event.get("id") == "req-1" and event.get("success")
        for event in events
    )


@respx.mock
def test_runtime_reopens_durable_checkpoint_with_prior_context(
    runtime_env: dict[str, Any],
    tmp_path: Path,
) -> None:
    route = respx.post(f"{UPSTREAM_BASE}/chat/completions").mock(
        side_effect=[_streaming_upstream_response(), _streaming_upstream_response()]
    )

    async def run() -> None:
        launcher = PiRuntimeLauncher()
        checkpoint_dir = tmp_path / "checkpoints"

        async def start(checkpoint_path: Path | None, generation: int) -> PiRuntimeHandle:
            return await launcher.start_session(
                provider_id=str(runtime_env["provider_id"]),
                model_id="gpt-test",
                model_context_window=200_000,
                model_max_tokens=8_192,
                model_reasoning=True,
                api_protocol="openai_chat_completions",
                proxy_url=str(runtime_env["proxy_url"]),
                proxy_token=str(runtime_env["proxy_token"]),
                workspace_root=Path(runtime_env["workspace_root"]),
                agent_session_id="durable-agent-session",
                runtime_generation=generation,
                checkpoint_dir=checkpoint_dir,
                checkpoint_path=checkpoint_path,
            )

        async def prompt_and_settle(handle: PiRuntimeHandle, prompt: str) -> None:
            await handle.send_command({"id": prompt, "type": "prompt", "message": prompt})
            events = handle.events()
            try:
                async with asyncio.timeout(30):
                    async for event in events:
                        if event.get("type") == "agent_settled":
                            return
                raise AssertionError("runtime did not settle")
            finally:
                await events.aclose()

        first = await start(None, 1)
        await prompt_and_settle(first, "Remember checkpoint marker alpha.")
        checkpoint_path = first.checkpoint_path
        assert checkpoint_path is not None and checkpoint_path.is_file()

        second = await start(checkpoint_path, 2)
        await prompt_and_settle(second, "What marker did I ask you to remember?")

    asyncio.run(run())

    assert route.call_count == 2
    second_payload = json.loads(route.calls[1].request.content)
    user_messages = [
        _user_text(message)
        for message in second_payload["messages"]
        if message.get("role") == "user"
    ]
    assert user_messages == [
        "Remember checkpoint marker alpha.",
        "What marker did I ask you to remember?",
    ]


@respx.mock
def test_abort_settles_session(runtime_env: dict[str, Any]) -> None:
    async def never_respond(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    respx.post(f"{UPSTREAM_BASE}/chat/completions").mock(side_effect=never_respond)

    async def on_started(handle: PiRuntimeHandle) -> None:
        await handle.send_command({"id": "req-prompt", "type": "prompt", "message": PROMPT_TEXT})

    async def on_event(handle: PiRuntimeHandle, event: dict[str, Any]) -> None:
        if event.get("type") == "agent_start":
            await handle.send_command({"id": "req-abort", "type": "abort"})

    events = asyncio.run(
        _drive_session(
            runtime_env,
            on_started,
            lambda event: event.get("type") == "agent_settled",
            on_event,
        )
    )

    event_names = [event.get("type") for event in events]
    assert "agent_start" in event_names
    assert "agent_settled" in event_names
    assert any(
        event.get("type") == "response" and event.get("id") == "req-abort" and event.get("success")
        for event in events
    )


@respx.mock
def test_immediate_abort_waits_for_prompt_preflight(runtime_env: dict[str, Any]) -> None:
    async def never_respond(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    respx.post(f"{UPSTREAM_BASE}/chat/completions").mock(side_effect=never_respond)

    async def on_started(handle: PiRuntimeHandle) -> None:
        await handle.send_command({"id": "req-prompt", "type": "prompt", "message": PROMPT_TEXT})
        await handle.send_command({"id": "req-abort", "type": "abort"})

    seen_terminal_events: set[str] = set()

    def stop_predicate(event: dict[str, Any]) -> bool:
        if event.get("type") == "agent_settled":
            seen_terminal_events.add("settled")
        if event.get("type") == "response" and event.get("id") == "req-abort":
            seen_terminal_events.add("abort_response")
        return seen_terminal_events == {"settled", "abort_response"}

    events = asyncio.run(
        _drive_session(
            runtime_env,
            on_started,
            stop_predicate,
            timeout=15.0,
        )
    )

    response_ids = [
        event.get("id")
        for event in events
        if event.get("type") == "response" and event.get("success")
    ]
    assert response_ids.index("req-prompt") < response_ids.index("req-abort")
    assert "agent_start" in {event.get("type") for event in events}


@pytest.mark.asyncio
async def test_send_command_drains_and_wraps_closed_pipe(tmp_path: Path) -> None:
    class RecordingStdin:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.drained = False

        def write(self, payload: bytes) -> None:
            self.writes.append(payload)

        async def drain(self) -> None:
            self.drained = True

    class BrokenStdin(RecordingStdin):
        async def drain(self) -> None:
            raise BrokenPipeError("closed")

    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        {
            "PI_SESSION_ID": "session-test",
            "PI_AGENT_SESSION_ID": "agent-session-test",
            "PI_RUNTIME_GENERATION": 1,
            "PI_CHECKPOINT_DIR": str(tmp_path),
        },
        tmp_path,
    )
    recording = RecordingStdin()
    handle._proc = SimpleNamespace(stdin=recording, returncode=None)  # type: ignore[assignment]

    await handle.send_command({"id": "one", "type": "prompt"})

    assert recording.writes == [b'{"id": "one", "type": "prompt"}\n']
    assert recording.drained is True

    handle._proc = SimpleNamespace(  # type: ignore[assignment]
        stdin=BrokenStdin(), returncode=None
    )
    with pytest.raises(PiRuntimeError, match="stdin closed"):
        await handle.send_command({"id": "two", "type": "abort"})
