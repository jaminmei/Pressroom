from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from sandbox_protocol import framing
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits, SandboxRequest


class _StubSupervisor:
    def execute_request(self, request: SandboxRequest):
        from sandbox_protocol.models import SandboxResponse, SandboxStatus

        return SandboxResponse(
            request_id=request.request_id,
            status=SandboxStatus.OK,
            result={"text": "ok", "binary": [], "structured": None, "metadata": {}},
            error=None,
            metrics={"wall_time_ms": 1},
        )

    def attestation(self, request_id: str):
        from sandbox_protocol.models import RunnerAttestationResponse, SandboxLimits

        return RunnerAttestationResponse(
            request_id=request_id,
            runner_reachable=True,
            attested=True,
            policy_digest=POLICY_DIGEST,
            network_policy="runner-network-none",
            limits=SandboxLimits().model_dump(mode="json"),
            version="1.0",
        )


class _PeerCheckingSupervisor(_StubSupervisor):
    def __init__(self) -> None:
        self.peer_uid: int | None = None

    def record_peer(self, uid: int) -> None:
        self.peer_uid = uid


class _BlockingSupervisor(_StubSupervisor):
    def __init__(self) -> None:
        self.release = threading.Event()
        self.child_calls = 0

    def execute_request(self, request: SandboxRequest):
        from sandbox_protocol.models import ErrorKind, ErrorPayload, SandboxResponse, SandboxStatus

        if self.child_calls == 0:
            self.child_calls += 1
            self.release.wait(timeout=1.0)
            return SandboxResponse(
                request_id=request.request_id,
                status=SandboxStatus.ERROR,
                result=None,
                error=ErrorPayload(kind=ErrorKind.TIMEOUT, message="request timed out"),
                metrics={"wall_time_ms": 100},
            )
        return SandboxResponse(
            request_id=request.request_id,
            status=SandboxStatus.ERROR,
            result=None,
            error=ErrorPayload(kind=ErrorKind.QUEUE_FULL, message="runner busy"),
            metrics={"wall_time_ms": 0},
        )


def test_runner_server_survives_malformed_frame_and_serves_next_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engines.adaptor_sandbox.runner.server import RunnerServer

    socket_path = tmp_path / "runner.sock"
    server = RunnerServer(socket_path=socket_path, supervisor=_StubSupervisor())
    monkeypatch.setattr(server, "_peer_uid", lambda conn: 10002)
    monkeypatch.setattr(server, "_approved_peer_uid", lambda: 10002)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while True:
        if time.time() > deadline:
            raise AssertionError("runner socket did not become ready")
        if socket_path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.connect(str(socket_path))
                break
            except OSError:
                pass
        time.sleep(0.05)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as malformed:
        malformed.connect(str(socket_path))
        malformed.sendall(b"\x00\x00\x00\x05{}")

    request = SandboxRequest(
        request_id="req-next",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as good:
        good.connect(str(socket_path))
        framing.send_frame(good, request, max_bytes=request.limits.max_request_bytes)
        frame = framing.recv_frame(good, max_bytes=request.limits.max_response_bytes)

    response = framing.decode_message(
        frame,
        type(_StubSupervisor().execute_request(request)),
        max_bytes=1_048_576,
    )
    assert response.request_id == "req-next"


def test_runner_server_rejects_unapproved_peer_uid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engines.adaptor_sandbox.runner.server import RunnerServer

    socket_path = tmp_path / "runner.sock"
    supervisor = _PeerCheckingSupervisor()
    server = RunnerServer(socket_path=socket_path, supervisor=supervisor)
    monkeypatch.setattr(server, "_peer_uid", lambda conn: 99999)
    monkeypatch.setattr(server, "_approved_peer_uid", lambda: 10002)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not socket_path.exists():
        if time.time() > deadline:
            raise AssertionError("runner socket did not appear")
        time.sleep(0.05)

    request = SandboxRequest(
        request_id="req-peer",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        framing.send_frame(client, request, max_bytes=request.limits.max_request_bytes)
        with pytest.raises((ConnectionResetError, BrokenPipeError, framing.FrameError, OSError)):
            framing.recv_frame(client, max_bytes=request.limits.max_response_bytes)


def test_runner_server_services_attestation_while_execute_is_in_flight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engines.adaptor_sandbox.runner.server import RunnerServer
    from sandbox_protocol.models import (
        RunnerAttestationRequest,
        RunnerAttestationResponse,
        SandboxResponse,
    )

    socket_path = tmp_path / "runner.sock"
    supervisor = _BlockingSupervisor()
    server = RunnerServer(socket_path=socket_path, supervisor=supervisor)
    monkeypatch.setattr(server, "_peer_uid", lambda conn: 10002)
    monkeypatch.setattr(server, "_approved_peer_uid", lambda: 10002)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not socket_path.exists():
        if time.time() > deadline:
            raise AssertionError("runner socket did not appear")
        time.sleep(0.05)

    request = SandboxRequest(
        request_id="req-exec",
        code="def main(inputs):\n    while True:\n        pass",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )
    attestation = RunnerAttestationRequest(request_id="req-attest")

    exec_result: dict[str, object] = {}

    def run_execute() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(socket_path))
            framing.send_frame(client, request, max_bytes=request.limits.max_request_bytes)
            frame = framing.recv_frame(client, max_bytes=request.limits.max_response_bytes)
            exec_result["response"] = framing.decode_message(
                frame,
                SandboxResponse,
                max_bytes=request.limits.max_response_bytes,
            )

    exec_thread = threading.Thread(target=run_execute)
    exec_thread.start()
    time.sleep(0.1)

    start = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        framing.send_frame(client, attestation, max_bytes=4096)
        frame = framing.recv_frame(client, max_bytes=1_048_576)
    elapsed = time.monotonic() - start
    attestation_response = framing.decode_message(
        frame,
        RunnerAttestationResponse,
        max_bytes=1_048_576,
    )

    assert elapsed < 1.0
    assert attestation_response.request_id == "req-attest"

    supervisor.release.set()
    exec_thread.join(timeout=2.0)


def test_runner_server_rejects_second_execute_promptly_while_first_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engines.adaptor_sandbox.runner.server import RunnerServer
    from sandbox_protocol.models import SandboxResponse

    socket_path = tmp_path / "runner.sock"
    supervisor = _BlockingSupervisor()
    server = RunnerServer(socket_path=socket_path, supervisor=supervisor)
    monkeypatch.setattr(server, "_peer_uid", lambda conn: 10002)
    monkeypatch.setattr(server, "_approved_peer_uid", lambda: 10002)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not socket_path.exists():
        if time.time() > deadline:
            raise AssertionError("runner socket did not appear")
        time.sleep(0.05)

    request = SandboxRequest(
        request_id="req-exec-one",
        code="def main(inputs):\n    while True:\n        pass",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )
    second_request = SandboxRequest(
        request_id="req-exec-two",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )

    def run_first() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(socket_path))
            framing.send_frame(client, request, max_bytes=request.limits.max_request_bytes)
            framing.recv_frame(client, max_bytes=request.limits.max_response_bytes)

    first_thread = threading.Thread(target=run_first)
    first_thread.start()
    time.sleep(0.1)

    start = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        framing.send_frame(
            client,
            second_request,
            max_bytes=second_request.limits.max_request_bytes,
        )
        frame = framing.recv_frame(client, max_bytes=second_request.limits.max_response_bytes)
    elapsed = time.monotonic() - start
    response = framing.decode_message(frame, SandboxResponse, max_bytes=1_048_576)

    assert elapsed < 1.0
    assert response.error is not None
    assert response.error.kind.value == "queue_full"
    assert supervisor.child_calls == 1

    supervisor.release.set()
    first_thread.join(timeout=2.0)
