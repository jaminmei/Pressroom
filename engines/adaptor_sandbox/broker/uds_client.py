from __future__ import annotations

import socket
import stat
from pathlib import Path
from typing import Any

from sandbox_protocol import framing
from sandbox_protocol.models import (
    RunnerAttestationRequest,
    RunnerAttestationResponse,
    SandboxRequest,
    SandboxResponse,
)


class RunnerUnavailableError(RuntimeError):
    pass


class RunnerUdsClient:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path

    def health(self) -> dict[str, Any]:
        try:
            response = self.attestation("runner-attestation")
        except RunnerUnavailableError:
            return {"runner_reachable": False, "attested": False}
        return response

    def attestation(self, request_id: str) -> dict[str, Any]:
        request = RunnerAttestationRequest(request_id=request_id)
        response = self._round_trip(request, max_request_bytes=4096, max_response_bytes=1_048_576)
        parsed = RunnerAttestationResponse.model_validate(response)
        return parsed.model_dump(mode="json")

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = SandboxRequest.model_validate(payload)
        return self._round_trip(
            request,
            max_request_bytes=request.limits.max_request_bytes,
            max_response_bytes=request.limits.max_response_bytes,
        )

    def _round_trip(
        self,
        request: Any,
        *,
        max_request_bytes: int,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        if self.socket_path.is_symlink():
            raise RunnerUnavailableError("runner socket path is invalid")
        if not self.socket_path.exists():
            raise RunnerUnavailableError("runner socket unavailable")
        stat_info = self.socket_path.stat()
        if not stat.S_ISSOCK(stat_info.st_mode):
            raise RunnerUnavailableError("runner socket unavailable")
        if stat_info.st_uid != 10001:
            raise RunnerUnavailableError("runner socket ownership mismatch")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(8.5)
            client.connect(str(self.socket_path))
            framing.send_frame(client, request, max_bytes=max_request_bytes)
            frame = framing.recv_frame(client, max_bytes=max_response_bytes)
        response = framing.decode_message(frame, type_hint(request), max_bytes=max_response_bytes)
        return response.model_dump(mode="json")


def type_hint(request: Any) -> type[SandboxResponse] | type[RunnerAttestationResponse]:
    if isinstance(request, RunnerAttestationRequest):
        return RunnerAttestationResponse
    return SandboxResponse
