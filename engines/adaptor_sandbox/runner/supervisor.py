from __future__ import annotations

import ast
import json
import os
import resource
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import BinaryIO, cast

from pydantic import ValidationError

from sandbox_protocol.models import (
    POLICY_DIGEST,
    ErrorKind,
    ErrorPayload,
    NodeOutputPayload,
    RunnerAttestationResponse,
    SandboxLimits,
    SandboxRequest,
    SandboxResponse,
    SandboxStatus,
    validate_output_payload,
)

_FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.ClassDef,
    ast.Lambda,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.With,
    ast.AsyncWith,
    ast.Global,
    ast.Nonlocal,
)
_FORBIDDEN_CALL_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "help",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
}
_CHILD_ENTRYPOINT = Path(__file__).with_name("child_entrypoint.py")


class AstPolicyError(ValueError):
    pass


class SocketPathError(ValueError):
    pass


def cleanup_stale_socket(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        raise SocketPathError("socket path must not be a symlink")
    mode = path.lstat().st_mode
    if not stat.S_ISSOCK(mode):
        raise SocketPathError("socket path is not a unix socket")
    path.unlink()


def validate_user_code(label: str, request: SandboxRequest) -> None:
    try:
        tree = ast.parse(request.code, filename=label)
    except SyntaxError as exc:
        raise AstPolicyError("invalid python syntax") from exc
    if sum(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body) != 1:
        raise AstPolicyError("exactly one top-level main function is required")
    if len(list(ast.walk(tree))) > request.limits.max_ast_nodes:
        raise AstPolicyError("ast exceeds node limit")

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_AST_NODES):
            raise AstPolicyError("forbidden python construct")
        if isinstance(node, ast.FunctionDef) and node.name.startswith("__"):
            raise AstPolicyError("dunder names are forbidden")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise AstPolicyError("dunder attributes are forbidden")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_CALL_NAMES
        ):
            raise AstPolicyError("forbidden builtin call")


class RunnerSupervisor:
    def __init__(self, *, socket_dir: Path) -> None:
        self.socket_dir = socket_dir
        self._approved_limits = SandboxLimits()
        self._execution_lock = threading.Lock()

    def execute_request(self, request: SandboxRequest) -> SandboxResponse:
        if request.policy_digest != POLICY_DIGEST:
            return self._error(request.request_id, ErrorKind.PROTOCOL, "policy digest mismatch")
        if request.limits != self._approved_limits:
            return self._error(request.request_id, ErrorKind.PROTOCOL, "policy limits mismatch")
        if not self._execution_lock.acquire(blocking=False):
            return self._error(request.request_id, ErrorKind.QUEUE_FULL, "runner busy")
        try:
            validate_user_code(request.request_id, request)
        except AstPolicyError:
            self._execution_lock.release()
            return self._error(request.request_id, ErrorKind.CODE, "code violates sandbox policy")

        try:
            return self._run_child(request)
        finally:
            self._execution_lock.release()

    def attestation(self, request_id: str) -> RunnerAttestationResponse:
        return RunnerAttestationResponse(
            request_id=request_id,
            runner_reachable=True,
            attested=True,
            policy_digest=POLICY_DIGEST,
            network_policy="runner-network-none",
            limits=self._approved_limits.model_dump(mode="json"),
            version="1.0",
        )

    def _run_child(self, request: SandboxRequest) -> SandboxResponse:
        with tempfile.TemporaryDirectory() as tmpdir:
            start = time.monotonic()
            stdin_payload = json.dumps(
                {
                    "code": request.code,
                    "inputs": {
                        name: payload.model_dump(mode="json")
                        for name, payload in request.inputs.items()
                    },
                    "recursion_limit": request.limits.recursion_limit,
                    "limits": request.limits.model_dump(mode="json"),
                },
                separators=(",", ":"),
            )
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", str(_CHILD_ENTRYPOINT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmpdir,
                env={"PYTHONIOENCODING": "utf-8"},
                start_new_session=True,
                preexec_fn=self._apply_child_limits,
            )
            timeout_seconds = max(request.limits.wall_timeout_ms / 1000.0, 0.05)
            try:
                stdout = self._run_bounded_child(process, stdin_payload, timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                return self._error(request.request_id, ErrorKind.TIMEOUT, "request timed out")
            except ValueError:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                return self._error(
                    request.request_id,
                    ErrorKind.RESOURCE,
                    "resource limit exceeded",
                )

        wall_time_ms = int((time.monotonic() - start) * 1000)
        if process.returncode != 0:
            try:
                error_payload = json.loads(stdout) if stdout else None
            except json.JSONDecodeError:
                error_payload = None
            if (
                isinstance(error_payload, dict)
                and error_payload.get("kind") == "resource"
                and error_payload.get("message") == "resource limit exceeded"
            ):
                return self._error(
                    request.request_id,
                    ErrorKind.RESOURCE,
                    "resource limit exceeded",
                    wall_time_ms,
                )
            return self._error(
                request.request_id,
                ErrorKind.RUNTIME,
                "sandbox execution failed",
                wall_time_ms,
            )
        # stdout is the complete JSON response.  Binary output is base64-encoded
        # here, so the response budget (not the small control-stream budget)
        # is the applicable limit.
        if len(stdout.encode("utf-8")) > request.limits.max_response_bytes:
            return self._error(
                request.request_id,
                ErrorKind.RESOURCE,
                "resource limit exceeded",
                wall_time_ms,
            )
        try:
            payload = NodeOutputPayload.model_validate_json(stdout)
        except ValidationError:
            return self._error(
                request.request_id,
                ErrorKind.RUNTIME,
                "sandbox returned invalid output",
                wall_time_ms,
            )
        try:
            validate_output_payload(payload.model_dump(mode="json"), self._approved_limits)
        except ValueError:
            return self._error(
                request.request_id,
                ErrorKind.RESOURCE,
                "resource limit exceeded",
                wall_time_ms,
            )
        return SandboxResponse(
            request_id=request.request_id,
            status=SandboxStatus.OK,
            result=payload,
            error=None,
            metrics={"wall_time_ms": wall_time_ms},
        )

    def _apply_child_limits(self) -> None:
        self._set_rlimit(resource.RLIMIT_CPU, self._approved_limits.max_cpu_seconds)
        self._set_rlimit(resource.RLIMIT_AS, self._approved_limits.max_address_space_bytes)
        self._set_rlimit(resource.RLIMIT_FSIZE, self._approved_limits.max_fsize_bytes)
        self._set_rlimit(resource.RLIMIT_NOFILE, self._approved_limits.max_nofile)
        self._set_rlimit(resource.RLIMIT_NPROC, self._approved_limits.max_nproc)
        self._set_rlimit(resource.RLIMIT_CORE, 0)
        if hasattr(resource, "RLIMIT_STACK"):
            self._set_rlimit(
                resource.RLIMIT_STACK,
                min(8 * 1024 * 1024, self._approved_limits.max_address_space_bytes),
            )

    @staticmethod
    def _set_rlimit(limit_key: int, requested: int) -> None:
        soft, hard = resource.getrlimit(limit_key)
        capped = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        resource.setrlimit(limit_key, (capped, capped))

    def _run_bounded_child(
        self,
        process: subprocess.Popen[bytes],
        stdin_payload: str,
        timeout_seconds: float,
    ) -> str:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        process.stdin.write(stdin_payload.encode("utf-8"))
        process.stdin.close()

        stdout_reader = cast(BinaryIO, process.stdout)
        stderr_reader = cast(BinaryIO, process.stderr)

        selector = selectors.DefaultSelector()
        selector.register(stdout_reader, selectors.EVENT_READ, data="stdout")
        selector.register(stderr_reader, selectors.EVENT_READ, data="stderr")
        stdout_chunks = bytearray()
        stderr_chunks = bytearray()
        deadline = time.monotonic() + timeout_seconds

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            events = selector.select(timeout=remaining)
            if not events:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            for key, _ in events:
                reader = cast(BinaryIO, key.fileobj)
                chunk = reader.read(1024)
                if not chunk:
                    selector.unregister(reader)
                    continue
                if key.data == "stdout":
                    stdout_chunks.extend(chunk)
                    if len(stdout_chunks) > self._approved_limits.max_response_bytes:
                        raise ValueError("stdout exceeded limit")
                else:
                    stderr_chunks.extend(chunk)
                    if len(stderr_chunks) > self._approved_limits.max_stdio_bytes:
                        raise ValueError("stderr exceeded limit")

        process.wait(timeout=max(deadline - time.monotonic(), 0.01))
        return stdout_chunks.decode("utf-8")

    def _error(
        self,
        request_id: str,
        kind: ErrorKind,
        message: str,
        wall_time_ms: int = 0,
    ) -> SandboxResponse:
        return SandboxResponse(
            request_id=request_id,
            status=SandboxStatus.ERROR,
            result=None,
            error=ErrorPayload(kind=kind, message=message),
            metrics={"wall_time_ms": wall_time_ms},
        )
