from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import app.services.pi_runtime as pi_runtime_module
from app.services.pi_runtime import (
    PiRuntimeError,
    PiRuntimeHandle,
    PiRuntimeLauncher,
    PiRuntimeServiceHandle,
)


def _bootstrap(tmp_path: Path, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "PI_SESSION_ID": "session-test",
        "PI_AGENT_SESSION_ID": "agent-session-test",
        "PI_RUNTIME_GENERATION": 1,
        "PI_CHECKPOINT_DIR": str(tmp_path),
    }
    values.update(overrides)
    return values


def _ready(tmp_path: Path) -> bytes:
    return (
        json.dumps(
            {
                "type": "runtime_ready",
                "checkpoint_ref": str(tmp_path / "session.jsonl"),
                "checkpoint_schema_version": 3,
            }
        ).encode("utf-8")
        + b"\n"
    )


def _remote_bootstrap(tmp_path: Path) -> dict[str, object]:
    return {
        "PI_PROVIDER_ID": "provider-a",
        "PI_MODEL_ID": "model-a",
        "PI_MODEL_CONTEXT_WINDOW": 32_000,
        "PI_MODEL_MAX_TOKENS": 4_096,
        "PI_MODEL_REASONING": False,
        "PI_API_PROTOCOL": "openai_chat_completions",
        "PI_PROXY_URL": "http://backend:8000/internal/proxy/invoke/provider-a",
        "PI_PROXY_TOKEN": "proxy-grant",
        "PI_WORKSPACE_ROOT": str(tmp_path),
        "PI_SESSION_ID": "runtime-a",
        "PI_AGENT_SESSION_ID": "agent-a",
        "PI_RUNTIME_GENERATION": 2,
        "PI_CHECKPOINT_DIR": str(tmp_path),
        "PI_TOOL_GATEWAY_URL": "http://backend:8000/internal/agent-tools/execute",
        "PI_TOOL_GATEWAY_GRANT": "gateway-grant",
        "PI_TOOL_CATALOG_VERSION": "0.1",
    }


class _RecordingStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        pass


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line

    def __aiter__(self) -> _FakeStdout:
        return self

    async def __anext__(self) -> bytes:
        line = await self.readline()
        if not line:
            raise StopAsyncIteration
        return line


class _CrashedProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _FakeStdout(lines)
        self.stderr = None
        self.stdin = None
        self.returncode: int | None = None
        self.terminated = False
        self.pid = 4321

    async def wait(self) -> int:
        self.returncode = 1
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class _HandshakeProcess(_CrashedProcess):
    def __init__(self, lines: list[bytes]) -> None:
        super().__init__(lines)
        self.stdin = _RecordingStdin()


@pytest.mark.asyncio
async def test_start_bootstraps_over_stdin_without_pi_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = _bootstrap(
        tmp_path,
        PI_PROVIDER_ID="provider-test",
        PI_MODEL_ID="model-test",
        PI_MODEL_CONTEXT_WINDOW=200_000,
        PI_MODEL_MAX_TOKENS=8_192,
        PI_MODEL_REASONING=True,
        PI_API_PROTOCOL="openai_chat_completions",
        PI_PROXY_URL="http://proxy.invalid",
        PI_PROXY_TOKEN="sensitive-grant",
        PI_WORKSPACE_ROOT=str(tmp_path),
    )
    process = _HandshakeProcess([_ready(tmp_path)])
    expected_bootstrap = bootstrap.copy()
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _HandshakeProcess:
        captured["command"] = command
        captured.update(kwargs)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    handle = PiRuntimeHandle(["node", "runtime.mjs"], bootstrap, tmp_path)

    await handle.start()

    assert captured["env"] == {
        "PATH": pi_runtime_module._RUNTIME_TOOL_PATH,
        "PI_OFFLINE": "1",
    }
    assert "sensitive-grant" not in " ".join(captured["command"])  # type: ignore[arg-type]
    assert json.loads(process.stdin.writes[0]) == expected_bootstrap  # type: ignore[union-attr]
    assert bootstrap["PI_CHECKPOINT_PATH"] == str(tmp_path / "session.jsonl")
    assert handle.state == "running"
    await handle.stop()


@pytest.mark.asyncio
async def test_start_waits_for_previous_stderr_drain_to_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _HandshakeProcess([_ready(tmp_path)])
    previous_drain_finished = asyncio.Event()

    async def previous_drain() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            previous_drain_finished.set()

    async def fake_create_subprocess_exec(
        *_command: str,
        **_kwargs: object,
    ) -> _HandshakeProcess:
        assert previous_drain_finished.is_set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )
    handle._stderr_task = asyncio.create_task(previous_drain())
    await asyncio.sleep(0)

    await handle.start()

    assert previous_drain_finished.is_set()
    await handle.stop()


@pytest.mark.asyncio
async def test_start_rejects_malformed_ready_handshake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _HandshakeProcess([b'{"type":"response","success":true}\n'])

    async def fake_create_subprocess_exec(*_command: str, **_kwargs: object) -> _HandshakeProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )

    with pytest.raises(PiRuntimeError, match="failed to start"):
        await handle.start()

    assert process.terminated is True
    assert handle.state == "dead"


@pytest.mark.asyncio
async def test_start_times_out_waiting_for_ready_handshake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BlockingStdout(_FakeStdout):
        async def readline(self) -> bytes:
            await asyncio.Event().wait()
            return b""

    process = _HandshakeProcess([])
    process.stdout = _BlockingStdout([])

    async def fake_create_subprocess_exec(*_command: str, **_kwargs: object) -> _HandshakeProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(pi_runtime_module, "_RUNTIME_BOOTSTRAP_TIMEOUT_SECONDS", 0.01)
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )

    with pytest.raises(PiRuntimeError, match="failed to start"):
        await handle.start()

    assert process.terminated is True
    assert handle.state == "dead"


@pytest.mark.asyncio
async def test_send_command_rejects_oversized_payload_without_leaking_it(tmp_path: Path) -> None:
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )
    stdin = _RecordingStdin()
    handle._proc = SimpleNamespace(stdin=stdin, returncode=None)  # type: ignore[assignment]
    secret = "sensitive-value-" + ("x" * 1_048_576)

    with pytest.raises(PiRuntimeError, match="command exceeds size limit") as exc_info:
        await handle.send_command({"id": "oversized", "message": secret})

    assert "sensitive-value" not in str(exc_info.value)
    assert stdin.writes == []


@pytest.mark.asyncio
async def test_start_oserror_marks_handle_dead_and_raises_runtime_error(tmp_path: Path) -> None:
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )

    async def fail_start() -> None:
        raise OSError("sensitive executable path")

    handle.start = fail_start  # type: ignore[method-assign]

    with pytest.raises(PiRuntimeError, match="failed to start") as exc_info:
        await anext(handle.events())

    assert "sensitive executable path" not in str(exc_info.value)
    assert handle.state == "dead"


@pytest.mark.asyncio
async def test_launcher_sanitizes_initial_subprocess_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_start(_handle: PiRuntimeHandle) -> None:
        raise OSError("sensitive executable path")

    monkeypatch.setattr(PiRuntimeHandle, "start", fail_start)
    launcher = PiRuntimeLauncher(node_bin=sys.executable)

    with pytest.raises(PiRuntimeError, match="failed to start") as exc_info:
        await launcher.start_session(
            provider_id="provider-1",
            model_id="model-1",
            model_context_window=200_000,
            model_max_tokens=8_192,
            model_reasoning=True,
            api_protocol="openai_chat_completions",
            proxy_url="http://proxy.invalid",
            proxy_token="sensitive-token",
            workspace_root=tmp_path,
        )

    assert "sensitive executable path" not in str(exc_info.value)
    assert "sensitive-token" not in str(exc_info.value)
    assert launcher._handles == {}


@pytest.mark.asyncio
async def test_child_stream_error_marks_handle_dead(tmp_path: Path) -> None:
    class BrokenStdout:
        def __aiter__(self) -> BrokenStdout:
            return self

        async def __anext__(self) -> bytes:
            raise OSError("sensitive pipe detail")

    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )
    process = _CrashedProcess([])
    process.stdout = BrokenStdout()  # type: ignore[assignment]

    async def fake_start() -> None:
        handle._proc = process  # type: ignore[assignment]

    handle.start = fake_start  # type: ignore[method-assign]

    with pytest.raises(PiRuntimeError, match="event stream failed") as exc_info:
        await anext(handle.events())

    assert "sensitive pipe detail" not in str(exc_info.value)
    assert process.terminated is True
    assert handle.state == "dead"


@pytest.mark.asyncio
async def test_closing_event_consumer_stops_child_process(tmp_path: Path) -> None:
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )
    process = _CrashedProcess([b'{"type":"agent_start"}\n'])
    handle._proc = process  # type: ignore[assignment]
    events = handle.events()

    assert await anext(events) == {"type": "agent_start"}
    await events.aclose()

    assert process.terminated is True
    assert handle.state == "stopped"
    assert handle._proc is None


@pytest.mark.asyncio
async def test_closing_event_consumer_unregisters_launcher_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_start(handle: PiRuntimeHandle) -> None:
        handle._state = "running"

    monkeypatch.setattr(PiRuntimeHandle, "start", fake_start)
    launcher = PiRuntimeLauncher(node_bin=sys.executable)
    handle = await launcher.start_session(
        provider_id="provider-1",
        model_id="model-1",
        model_context_window=200_000,
        model_max_tokens=8_192,
        model_reasoning=True,
        api_protocol="openai_chat_completions",
        proxy_url="http://proxy.invalid",
        proxy_token="sensitive-token",
        workspace_root=tmp_path,
    )
    process = _CrashedProcess([b'{"type":"agent_start"}\n'])
    handle._proc = process  # type: ignore[assignment]
    events = handle.events()

    assert handle.session_id in launcher._handles
    assert await anext(events) == {"type": "agent_start"}
    await events.aclose()

    assert launcher._handles == {}


@pytest.mark.asyncio
async def test_shutdown_all_continues_after_unexpected_stop_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    class FakeHandle:
        def __init__(self, session_id: str, *, fail: bool) -> None:
            self.session_id = session_id
            self.fail = fail

        async def stop(self) -> None:
            calls.append(self.session_id)
            if self.fail:
                raise RuntimeError("sensitive runtime state")

    launcher = PiRuntimeLauncher(node_bin=sys.executable)
    launcher._handles = {  # type: ignore[assignment]
        "broken": FakeHandle("broken", fail=True),
        "healthy": FakeHandle("healthy", fail=False),
    }

    with caplog.at_level("WARNING", logger="app.services.pi_runtime"):
        await launcher.shutdown_all()

    assert calls == ["broken", "healthy"]
    assert launcher._handles == {}
    assert "error_type=RuntimeError" in caplog.text
    assert "sensitive runtime state" not in caplog.text


@pytest.mark.asyncio
async def test_settled_run_resets_consecutive_crash_attempts(tmp_path: Path) -> None:
    handle = PiRuntimeHandle(
        ["node", "runtime.mjs"],
        _bootstrap(tmp_path),
        tmp_path,
    )
    process_lines = [
        [],
        [b'{"type":"agent_settled"}\n'],
        [],
        [],
        [],
    ]
    start_count = 0

    async def fake_start() -> None:
        nonlocal start_count
        handle._proc = _CrashedProcess(process_lines[start_count])  # type: ignore[assignment]
        start_count += 1

    handle.start = fake_start  # type: ignore[method-assign]
    events = handle.events()

    assert await anext(events) == {"type": "agent_settled"}
    with pytest.raises(PiRuntimeError, match="crashed 4 times"):
        async for _event in events:
            pass

    assert start_count == 5
    assert handle.state == "dead"


@pytest.mark.asyncio
async def test_remote_runtime_handle_authenticates_and_tracks_event_cursor(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    event_polls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal event_polls
        requests.append(request)
        assert request.headers["x-pi-runtime-control"] == "control-token"
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(
                201,
                json={
                    "session_id": "runtime-a",
                    "checkpoint_ref": str(tmp_path / "session.jsonl"),
                    "checkpoint_schema_version": 3,
                    "runtime_generation": 2,
                },
            )
        if request.method == "POST" and request.url.path.endswith("/commands"):
            return httpx.Response(202, json={"accepted": True})
        if request.method == "GET" and request.url.path.endswith("/events"):
            event_polls += 1
            if event_polls == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"sequence": 1, "event": {"type": "runtime_ready"}},
                            {"sequence": 2, "event": {"type": "agent_start"}},
                        ],
                        "state": "running",
                    },
                )
            return httpx.Response(200, json={"items": [], "state": "stopped"})
        raise AssertionError(f"unexpected Runtime service request: {request.method} {request.url}")

    handle = PiRuntimeServiceHandle(
        service_url="http://pi-runtime:8080",
        control_token="control-token",
        bootstrap=_remote_bootstrap(tmp_path),  # type: ignore[arg-type]
    )
    await handle._client.aclose()
    handle._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    await handle.start()
    await handle.send_command({"id": "prompt-a", "type": "prompt", "message": "workflow list"})
    events = handle.events()
    assert await anext(events) == {"type": "agent_start"}
    with pytest.raises(StopAsyncIteration):
        await anext(events)

    event_requests = [request for request in requests if request.url.path.endswith("/events")]
    assert [request.url.params["after"] for request in event_requests] == ["0", "2"]
    assert handle.state == "stopped"
    assert handle._client.is_closed


@pytest.mark.asyncio
async def test_remote_runtime_rejects_checkpoint_outside_session_boundary(tmp_path: Path) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "session_id": "runtime-a",
                "checkpoint_ref": str(tmp_path.parent / "escaped.jsonl"),
                "checkpoint_schema_version": 3,
                "runtime_generation": 2,
            },
        )

    handle = PiRuntimeServiceHandle(
        service_url="http://pi-runtime:8080",
        control_token="control-token",
        bootstrap=_remote_bootstrap(tmp_path),  # type: ignore[arg-type]
    )
    await handle._client.aclose()
    handle._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    with pytest.raises(PiRuntimeError, match="failed to start"):
        await handle.start()

    assert handle.state == "dead"
    assert handle._client.is_closed
