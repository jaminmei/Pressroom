from __future__ import annotations

import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor, cleanup_stale_socket
from sandbox_protocol import framing
from sandbox_protocol.models import (
    ErrorKind,
    ErrorPayload,
    RunnerAttestationRequest,
    SandboxRequest,
    SandboxResponse,
    SandboxStatus,
)

_MAX_HANDLER_WORKERS = 4


class RunnerServer:
    def __init__(self, *, socket_path: Path, supervisor: RunnerSupervisor) -> None:
        self.socket_path = socket_path
        self.supervisor = supervisor
        self._handler_slots = threading.BoundedSemaphore(value=_MAX_HANDLER_WORKERS)
        self._handler_executor = ThreadPoolExecutor(
            max_workers=_MAX_HANDLER_WORKERS,
            thread_name_prefix="runner-uds",
        )
        self._execution_admission = threading.Lock()
        self._active_handlers = 0
        self._active_handlers_lock = threading.Lock()
        self._server_socket: socket.socket | None = None
        self._shutdown = threading.Event()

    def serve_forever(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        cleanup_stale_socket(self.socket_path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            self._server_socket = server
            server.bind(str(self.socket_path))
            self.socket_path.chmod(0o660)
            server.listen(_MAX_HANDLER_WORKERS)
            while not self._shutdown.is_set():
                try:
                    conn, _ = server.accept()
                except OSError:
                    if self._shutdown.is_set():
                        break
                    continue
                if not self._handler_slots.acquire(blocking=False):
                    conn.close()
                    continue
                self._handler_executor.submit(self._handle_connection, conn)

        self._handler_executor.shutdown(wait=True)
        self._server_socket = None
        if self.socket_path.exists():
            self.socket_path.unlink()

    def close(self) -> None:
        self._shutdown.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _handle_connection(self, conn: socket.socket) -> None:
        self._increment_active_handlers()
        try:
            with conn:
                conn.settimeout(8.5)
                try:
                    if self._peer_uid(conn) != self._approved_peer_uid():
                        conn.close()
                        return
                    frame = framing.recv_frame(conn, max_bytes=3_145_728)
                    request = self._decode_request(frame)
                    if isinstance(request, RunnerAttestationRequest):
                        framing.send_frame(
                            conn,
                            self.supervisor.attestation(request.request_id),
                            max_bytes=1_048_576,
                        )
                        return
                    if not self._execution_admission.acquire(blocking=False):
                        framing.send_frame(
                            conn,
                            self._queue_full_response(request.request_id),
                            max_bytes=1_048_576,
                        )
                        return
                    try:
                        response = self.supervisor.execute_request(request)
                    finally:
                        self._execution_admission.release()
                    framing.send_frame(conn, response, max_bytes=1_048_576)
                except (TimeoutError, OSError, ValueError):
                    return
        finally:
            self._decrement_active_handlers()
            self._handler_slots.release()

    def _increment_active_handlers(self) -> None:
        with self._active_handlers_lock:
            self._active_handlers += 1

    def _decrement_active_handlers(self) -> None:
        with self._active_handlers_lock:
            self._active_handlers -= 1

    @staticmethod
    def _queue_full_response(request_id: str) -> SandboxResponse:
        return SandboxResponse(
            request_id=request_id,
            status=SandboxStatus.ERROR,
            result=None,
            error=ErrorPayload(kind=ErrorKind.QUEUE_FULL, message="runner busy"),
            metrics={"wall_time_ms": 0},
        )

    @staticmethod
    def _decode_request(frame: bytes) -> SandboxRequest | RunnerAttestationRequest:
        try:
            request = framing.decode_message(frame, RunnerAttestationRequest, max_bytes=3_145_728)
            return RunnerAttestationRequest.model_validate(request.model_dump(mode="json"))
        except Exception:
            request = framing.decode_message(frame, SandboxRequest, max_bytes=3_145_728)
            return SandboxRequest.model_validate(request.model_dump(mode="json"))

    @staticmethod
    def _approved_peer_uid() -> int:
        return 10002

    @staticmethod
    def _peer_uid(conn: socket.socket) -> int:
        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", creds)
        return int(uid)


def main() -> None:
    socket_path = Path("/run/adaptor-sandbox/runner.sock")
    supervisor = RunnerSupervisor(socket_dir=socket_path.parent)
    RunnerServer(socket_path=socket_path, supervisor=supervisor).serve_forever()


if __name__ == "__main__":
    main()
