"""Node Pi runtime launcher and lifecycle supervision.

Starts the embedded-AgentSession Node runtime (``pi_runtime/src/main.mjs``),
streams its Pi ``AgentSessionEvent`` JSON lines, forwards RPC commands, and
supervises the child process. The child only ever receives the Provider id,
model id, ``api_protocol``, internal proxy address and invocation grant,
workspace root, and session id through a private stdin bootstrap frame — never
through env/argv/files, and never with the external Provider token or URL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import httpx

logger = logging.getLogger(__name__)

_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "pi_runtime"
_ENTRYPOINT = _RUNTIME_DIR / "src" / "main.mjs"

_STOP_GRACE_SECONDS = 5.0
_MAX_RESTART_ATTEMPTS = 3
_MAX_COMMAND_BYTES = 1_048_576
_MAX_BOOTSTRAP_BYTES = 1_048_576
_RUNTIME_BOOTSTRAP_TIMEOUT_SECONDS = 120.0
_RUNTIME_TOOL_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class PiRuntimeError(RuntimeError):
    """Raised when a Pi runtime session is unavailable or crashed for good."""


class PiRuntimeBootstrap(TypedDict):
    """Private stdin bootstrap contract shared with the Node runtime."""

    PI_PROVIDER_ID: str
    PI_MODEL_ID: str
    PI_MODEL_CONTEXT_WINDOW: int
    PI_MODEL_MAX_TOKENS: int
    PI_MODEL_REASONING: bool
    PI_API_PROTOCOL: str
    PI_PROXY_URL: str
    PI_PROXY_TOKEN: str
    PI_WORKSPACE_ROOT: str
    PI_SESSION_ID: str
    PI_AGENT_SESSION_ID: str
    PI_RUNTIME_GENERATION: int
    PI_CHECKPOINT_DIR: str
    PI_CHECKPOINT_PATH: NotRequired[str]
    PI_LEGACY_MESSAGES: NotRequired[list[dict[str, Any]]]
    PI_TOOL_GATEWAY_URL: str
    PI_TOOL_GATEWAY_GRANT: str
    PI_TOOL_CATALOG_VERSION: str


class PiRuntimeHandle:
    """A supervised Pi runtime child process bound to one chatbot session."""

    def __init__(
        self,
        command: list[str],
        bootstrap: PiRuntimeBootstrap,
        workspace_root: Path,
        on_stopped: Callable[[str], None] | None = None,
    ) -> None:
        self._command = command
        self._bootstrap = bootstrap
        self._workspace_root = workspace_root
        self.session_id = bootstrap["PI_SESSION_ID"]
        self.agent_session_id = bootstrap["PI_AGENT_SESSION_ID"]
        self.runtime_generation = bootstrap["PI_RUNTIME_GENERATION"]
        self.checkpoint_path: Path | None = None
        self.checkpoint_schema_version: int | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._state = "starting"
        self._stopping = False
        self._on_stopped = on_stopped
        self._stop_notified = False

    @property
    def state(self) -> str:
        """One of ``starting``, ``running``, ``restarting``, ``stopped``, ``dead``."""
        return self._state

    async def send_command(self, command: dict[str, Any]) -> None:
        """Write one Pi RPC JSON command to the child's stdin."""
        proc = self._proc
        if self._stopping or proc is None or proc.stdin is None or proc.returncode is not None:
            raise PiRuntimeError(f"pi runtime session {self.session_id} is not running")
        try:
            payload = json.dumps(command).encode("utf-8")
            if len(payload) > _MAX_COMMAND_BYTES:
                raise PiRuntimeError("pi runtime command exceeds size limit")
            proc.stdin.write(payload + b"\n")
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise PiRuntimeError(f"pi runtime session {self.session_id} stdin closed") from exc

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed Pi events from the child, restarting after crashes.

        Restarts up to ``_MAX_RESTART_ATTEMPTS`` times; after that the handle
        is ``dead`` and the consumer receives :class:`PiRuntimeError`. Closing
        or cancelling the consumer also owns cleanup of the child process.
        """
        try:
            async for event in self._events_without_cleanup():
                yield event
        finally:
            await self.stop()

    async def _events_without_cleanup(self) -> AsyncIterator[dict[str, Any]]:
        attempts = 0
        while True:
            if self._proc is None or self._proc.returncode is not None:
                try:
                    await self.start()
                except Exception as exc:
                    await self._mark_dead()
                    logger.error(
                        "pi runtime failed to start session=%s error_type=%s",
                        self.session_id,
                        type(exc).__name__,
                    )
                    raise PiRuntimeError(
                        f"pi runtime session {self.session_id} failed to start"
                    ) from exc
            proc = self._proc
            assert proc is not None and proc.stdout is not None
            self._state = "running"
            try:
                async for line in proc.stdout:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "pi runtime emitted an unparsable stdout line session=%s",
                            self.session_id,
                        )
                        continue
                    if isinstance(event, dict) and event.get("type") == "agent_settled":
                        attempts = 0
                    yield event
                exit_code = await proc.wait()
            except Exception as exc:
                await self._mark_dead()
                logger.error(
                    "pi runtime event stream failed session=%s error_type=%s",
                    self.session_id,
                    type(exc).__name__,
                )
                raise PiRuntimeError(
                    f"pi runtime session {self.session_id} event stream failed"
                ) from exc
            await self._cleanup_child()
            if self._stopping:
                self._state = "stopped"
                return
            attempts += 1
            if attempts > _MAX_RESTART_ATTEMPTS:
                self._state = "dead"
                logger.error(
                    "pi runtime session crashed for good session=%s exit_code=%s attempts=%s",
                    self.session_id,
                    exit_code,
                    attempts,
                )
                raise PiRuntimeError(
                    f"pi runtime session {self.session_id} crashed {attempts} times"
                )
            self._state = "restarting"
            logger.warning(
                "pi runtime crashed; restarting session=%s exit_code=%s attempt=%s",
                self.session_id,
                exit_code,
                attempts,
            )

    async def stop(self) -> None:
        """Abort the session and terminate the child (SIGTERM, grace, SIGKILL)."""
        self._stopping = True
        proc = self._proc
        try:
            if proc is not None and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_STOP_GRACE_SECONDS)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        finally:
            try:
                await self._cleanup_child()
            finally:
                if self._state != "dead":
                    self._state = "stopped"
                self._notify_stopped()
        logger.info("pi runtime stopped session=%s", self.session_id)

    async def start(self) -> None:
        try:
            await self._cancel_stderr_task()
            self._proc = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=str(self._workspace_root),
                # Configuration and the proxy grant must not appear in env,
                # argv, files, or /proc/<pid>/environ. The first stdin line is
                # a private bootstrap frame consumed before RPC commands.
                env={"PATH": _RUNTIME_TOOL_PATH, "PI_OFFLINE": "1"},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(self._proc), name=f"pi-runtime-stderr-{self.session_id}"
            )
            await self._bootstrap_child(self._proc)
        except asyncio.CancelledError:
            await self._mark_dead()
            raise
        except Exception as exc:
            await self._mark_dead()
            logger.error(
                "pi runtime bootstrap failed session=%s error_type=%s",
                self.session_id,
                type(exc).__name__,
            )
            raise PiRuntimeError(f"pi runtime session {self.session_id} failed to start") from exc
        self._state = "running"
        logger.info(
            "pi runtime started session=%s pid=%s",
            self.session_id,
            self._proc.pid,
        )

    async def _bootstrap_child(self, proc: asyncio.subprocess.Process) -> None:
        if proc.stdin is None or proc.stdout is None:
            raise PiRuntimeError("pi runtime bootstrap pipes are unavailable")
        payload = json.dumps(self._bootstrap, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MAX_BOOTSTRAP_BYTES:
            raise PiRuntimeError("pi runtime bootstrap exceeds size limit")
        proc.stdin.write(payload + b"\n")
        await proc.stdin.drain()
        line = await asyncio.wait_for(
            proc.stdout.readline(),
            timeout=_RUNTIME_BOOTSTRAP_TIMEOUT_SECONDS,
        )
        if not line or len(line) > _MAX_BOOTSTRAP_BYTES:
            raise PiRuntimeError("pi runtime bootstrap handshake failed")
        try:
            ready = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PiRuntimeError("pi runtime bootstrap handshake failed") from exc
        if not isinstance(ready, dict) or ready.get("type") != "runtime_ready":
            raise PiRuntimeError("pi runtime bootstrap handshake failed")
        checkpoint_ref = ready.get("checkpoint_ref")
        checkpoint_schema_version = ready.get("checkpoint_schema_version")
        if not isinstance(checkpoint_ref, str) or not checkpoint_ref:
            raise PiRuntimeError("pi runtime checkpoint handshake failed")
        checkpoint_path = Path(checkpoint_ref).resolve()
        checkpoint_dir = Path(self._bootstrap["PI_CHECKPOINT_DIR"]).resolve()
        if not checkpoint_path.is_relative_to(checkpoint_dir):
            raise PiRuntimeError("pi runtime checkpoint escaped its private boundary")
        if not isinstance(checkpoint_schema_version, int) or checkpoint_schema_version < 1:
            raise PiRuntimeError("pi runtime checkpoint schema is invalid")
        self.checkpoint_path = checkpoint_path
        self.checkpoint_schema_version = checkpoint_schema_version
        # Crash supervision must reopen the same durable session instead of
        # creating an empty conversation for the replacement child.
        self._bootstrap["PI_CHECKPOINT_PATH"] = str(checkpoint_path)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        # The child's stderr carries only its own controlled diagnostics.
        if proc.stderr is None:
            return
        async for line in proc.stderr:
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                logger.debug("pi runtime stderr session=%s line=%s", self.session_id, text)

    async def _cleanup_child(self) -> None:
        await self._cancel_stderr_task()
        self._proc = None

    async def _cancel_stderr_task(self) -> None:
        stderr_task = self._stderr_task
        self._stderr_task = None
        if stderr_task is not None:
            stderr_task.cancel()
            try:
                await asyncio.gather(stderr_task, return_exceptions=True)
            except asyncio.CancelledError:
                # Preserve cancellation of this cleanup operation; gather only
                # converts cancellation of the child task into a result.
                raise

    async def _mark_dead(self) -> None:
        self._stopping = True
        proc = self._proc
        try:
            if proc is not None and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_STOP_GRACE_SECONDS)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        except (OSError, ProcessLookupError):
            pass
        finally:
            try:
                await self._cleanup_child()
            finally:
                self._state = "dead"
                self._notify_stopped()

    def _notify_stopped(self) -> None:
        if self._stop_notified:
            return
        self._stop_notified = True
        if self._on_stopped is not None:
            self._on_stopped(self.session_id)


class PiRuntimeLauncher:
    """Creates supervised Pi runtime sessions.

    Registered lazily on ``app.state.pi_runtime_launcher``; the node binary is
    resolved from ``PI_NODE_BIN`` (default ``node``) and the runtime directory
    is resolved relative to the repository root.
    """

    def __init__(self, node_bin: str | None = None) -> None:
        candidate = node_bin or os.environ.get("PI_NODE_BIN", "node")
        resolved = shutil.which(candidate)
        if resolved is None:
            raise PiRuntimeError(f"node binary not found: {candidate}")
        # Use an absolute executable; the child receives only a fixed tool PATH
        # and Pi's offline guard. Session configuration travels over stdin.
        self._node_bin = resolved
        self._handles: dict[str, PiRuntimeHandle] = {}

    async def start_session(
        self,
        provider_id: str,
        model_id: str,
        model_context_window: int,
        model_max_tokens: int,
        model_reasoning: bool,
        api_protocol: str,
        proxy_url: str,
        proxy_token: str,
        workspace_root: Path,
        agent_session_id: str | None = None,
        runtime_generation: int = 1,
        checkpoint_dir: Path | None = None,
        checkpoint_path: Path | None = None,
        legacy_messages: list[dict[str, Any]] | None = None,
        tool_gateway_url: str = "http://127.0.0.1:8000/internal/agent-tools/execute",
        tool_gateway_grant: str = "test-only-unprivileged-grant",
        tool_catalog_version: str = "0.1",
    ) -> PiRuntimeHandle:
        """Start a Pi runtime child for one chatbot session.

        Only the Provider/model identifiers, validated model capabilities,
        api_protocol, internal proxy address and invocation grant, workspace
        root, and session id cross this boundary — never an external Provider
        token or URL.
        """
        session_id = uuid.uuid4().hex
        durable_session_id = agent_session_id or session_id
        durable_checkpoint_dir = checkpoint_dir or (
            Path(tempfile.gettempdir()) / "docconv-pi-runtime" / durable_session_id
        )
        durable_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        command = [self._node_bin, str(_ENTRYPOINT)]
        bootstrap: PiRuntimeBootstrap = {
            "PI_PROVIDER_ID": provider_id,
            "PI_MODEL_ID": model_id,
            "PI_MODEL_CONTEXT_WINDOW": model_context_window,
            "PI_MODEL_MAX_TOKENS": model_max_tokens,
            "PI_MODEL_REASONING": model_reasoning,
            "PI_API_PROTOCOL": api_protocol,
            "PI_PROXY_URL": proxy_url,
            "PI_PROXY_TOKEN": proxy_token,
            "PI_WORKSPACE_ROOT": str(workspace_root),
            "PI_SESSION_ID": session_id,
            "PI_AGENT_SESSION_ID": durable_session_id,
            "PI_RUNTIME_GENERATION": runtime_generation,
            "PI_CHECKPOINT_DIR": str(durable_checkpoint_dir),
            "PI_TOOL_GATEWAY_URL": tool_gateway_url,
            "PI_TOOL_GATEWAY_GRANT": tool_gateway_grant,
            "PI_TOOL_CATALOG_VERSION": tool_catalog_version,
        }
        if checkpoint_path is not None:
            bootstrap["PI_CHECKPOINT_PATH"] = str(checkpoint_path)
        elif legacy_messages:
            bootstrap["PI_LEGACY_MESSAGES"] = legacy_messages
        handle = PiRuntimeHandle(
            command,
            bootstrap,
            workspace_root,
            on_stopped=self._unregister_session,
        )
        try:
            await handle.start()
        except Exception as exc:
            await handle._mark_dead()
            logger.error(
                "pi runtime initial start failed session=%s error_type=%s",
                session_id,
                type(exc).__name__,
            )
            raise PiRuntimeError(f"pi runtime session {session_id} failed to start") from exc
        self._handles[session_id] = handle
        logger.info(
            "pi runtime session requested session=%s provider=%s model=%s protocol=%s",
            session_id,
            provider_id,
            model_id,
            api_protocol,
        )
        return handle

    async def shutdown_all(self) -> None:
        """Stop every live session (called from application shutdown)."""
        handles = list(self._handles.values())
        for handle in handles:
            try:
                await handle.stop()
            except Exception as exc:
                logger.warning(
                    "pi runtime stop failed session=%s error_type=%s",
                    handle.session_id,
                    type(exc).__name__,
                )
        self._handles.clear()

    def _unregister_session(self, session_id: str) -> None:
        self._handles.pop(session_id, None)

    async def stop_session(self, session_id: str) -> None:
        """Stop and forget one runtime session if it is still registered."""

        handle = self._handles.pop(session_id, None)
        if handle is not None:
            await handle.stop()


class PiRuntimeServiceHandle(PiRuntimeHandle):
    """Remote handle for a child owned by the isolated Pi Runtime service."""

    def __init__(
        self,
        *,
        service_url: str,
        control_token: str,
        bootstrap: PiRuntimeBootstrap,
        on_stopped: Callable[[str], None] | None = None,
    ) -> None:
        self._service_url = service_url.rstrip("/")
        self._headers = {"X-Pi-Runtime-Control": control_token}
        self._bootstrap = bootstrap
        self.session_id = bootstrap["PI_SESSION_ID"]
        self.agent_session_id = bootstrap["PI_AGENT_SESSION_ID"]
        self.runtime_generation = bootstrap["PI_RUNTIME_GENERATION"]
        self.checkpoint_path: Path | None = None
        self.checkpoint_schema_version: int | None = None
        self._state = "starting"
        self._cursor = 0
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=30.0))
        self._on_stopped = on_stopped
        self._stop_notified = False

    @property
    def state(self) -> str:
        return self._state

    async def start(self) -> None:
        failure_stage = "transport"
        failure_reason = "runtime_service_unavailable"
        try:
            encoded_bootstrap = json.dumps(
                self._bootstrap,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded_bootstrap) > _MAX_BOOTSTRAP_BYTES:
                raise PiRuntimeError("Pi Runtime service bootstrap exceeds size limit")
            response = await self._client.post(
                f"{self._service_url}/v1/sessions",
                headers=self._headers,
                json=self._bootstrap,
                timeout=130.0,
            )
            if response.is_error:
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = {}
                if isinstance(error_payload, dict):
                    stage = error_payload.get("stage")
                    reason = error_payload.get("reason_code")
                    if isinstance(stage, str) and stage.replace("_", "").isalnum():
                        failure_stage = stage
                    if isinstance(reason, str) and reason.replace("_", "").isalnum():
                        failure_reason = reason
            response.raise_for_status()
            payload = response.json()
            checkpoint_ref = payload.get("checkpoint_ref")
            checkpoint_schema_version = payload.get("checkpoint_schema_version")
            returned_generation = payload.get("runtime_generation")
            if not isinstance(checkpoint_ref, str) or not checkpoint_ref:
                raise PiRuntimeError("Pi Runtime service returned no checkpoint")
            checkpoint_path = Path(checkpoint_ref).resolve()
            checkpoint_dir = Path(self._bootstrap["PI_CHECKPOINT_DIR"]).resolve()
            if not checkpoint_path.is_relative_to(checkpoint_dir):
                raise PiRuntimeError("Pi Runtime service checkpoint escaped its boundary")
            if not isinstance(checkpoint_schema_version, int) or checkpoint_schema_version < 1:
                raise PiRuntimeError("Pi Runtime service checkpoint schema is invalid")
            if returned_generation != self.runtime_generation:
                raise PiRuntimeError("Pi Runtime service generation does not match")
            self.checkpoint_path = checkpoint_path
            self.checkpoint_schema_version = checkpoint_schema_version
            self._bootstrap["PI_CHECKPOINT_PATH"] = str(checkpoint_path)
            self._state = "running"
        except (httpx.HTTPError, ValueError, TypeError, PiRuntimeError) as exc:
            self._state = "dead"
            await self._client.aclose()
            logger.warning(
                "Pi Runtime service start rejected session=%s stage=%s reason=%s",
                self.session_id,
                failure_stage,
                failure_reason,
            )
            raise PiRuntimeError("Pi Runtime service failed to start a Session") from exc

    async def send_command(self, command: dict[str, Any]) -> None:
        if self._state != "running":
            raise PiRuntimeError(f"pi runtime session {self.session_id} is not running")
        payload = json.dumps(command).encode("utf-8")
        if len(payload) > _MAX_COMMAND_BYTES:
            raise PiRuntimeError("pi runtime command exceeds size limit")
        try:
            response = await self._client.post(
                f"{self._service_url}/v1/sessions/{self.session_id}/commands",
                headers=self._headers,
                json=command,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._state = "dead"
            raise PiRuntimeError("Pi Runtime service rejected a command") from exc

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        try:
            while self._state == "running":
                try:
                    response = await self._client.get(
                        f"{self._service_url}/v1/sessions/{self.session_id}/events",
                        headers=self._headers,
                        params={"after": self._cursor},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    self._state = "dead"
                    raise PiRuntimeError("Pi Runtime service event stream failed") from exc
                items = payload.get("items")
                if not isinstance(items, list):
                    self._state = "dead"
                    raise PiRuntimeError("Pi Runtime service returned malformed events")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    sequence = item.get("sequence")
                    event = item.get("event")
                    if isinstance(sequence, int) and sequence > self._cursor:
                        self._cursor = sequence
                    if isinstance(event, dict) and event.get("type") != "runtime_ready":
                        yield event
                state = payload.get("state")
                if state in {"dead", "stopped"}:
                    self._state = str(state)
                    await self._client.aclose()
                    self._notify_stopped()
                    if state == "dead":
                        raise PiRuntimeError("Pi Runtime service child terminated")
                    return
        finally:
            if self._state == "running":
                await self.stop()

    async def stop(self) -> None:
        previous = self._state
        self._state = "stopped"
        try:
            if previous not in {"dead", "stopped"}:
                response = await self._client.delete(
                    f"{self._service_url}/v1/sessions/{self.session_id}",
                    headers=self._headers,
                )
                if response.status_code not in {200, 404}:
                    response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "Pi Runtime service stop failed session=%s error_type=%s",
                self.session_id,
                type(exc).__name__,
            )
        finally:
            await self._client.aclose()
            self._notify_stopped()

    def _notify_stopped(self) -> None:
        if self._stop_notified:
            return
        self._stop_notified = True
        if self._on_stopped is not None:
            self._on_stopped(self.session_id)


class PiRuntimeServiceLauncher(PiRuntimeLauncher):
    """Creates Session children through the dedicated Runtime service."""

    def __init__(self, *, service_url: str, control_token: str) -> None:
        self._service_url = service_url
        self._control_token = control_token
        self._handles: dict[str, PiRuntimeHandle] = {}

    async def start_session(
        self,
        provider_id: str,
        model_id: str,
        model_context_window: int,
        model_max_tokens: int,
        model_reasoning: bool,
        api_protocol: str,
        proxy_url: str,
        proxy_token: str,
        workspace_root: Path,
        agent_session_id: str | None = None,
        runtime_generation: int = 1,
        checkpoint_dir: Path | None = None,
        checkpoint_path: Path | None = None,
        legacy_messages: list[dict[str, Any]] | None = None,
        tool_gateway_url: str = "http://backend:8000/internal/agent-tools/execute",
        tool_gateway_grant: str = "test-only-unprivileged-grant",
        tool_catalog_version: str = "0.1",
    ) -> PiRuntimeServiceHandle:
        del workspace_root
        session_id = uuid.uuid4().hex
        durable_session_id = agent_session_id or session_id
        durable_checkpoint_dir = checkpoint_dir or (
            Path(tempfile.gettempdir()) / "docconv-pi-runtime" / durable_session_id
        )
        durable_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        bootstrap: PiRuntimeBootstrap = {
            "PI_PROVIDER_ID": provider_id,
            "PI_MODEL_ID": model_id,
            "PI_MODEL_CONTEXT_WINDOW": model_context_window,
            "PI_MODEL_MAX_TOKENS": model_max_tokens,
            "PI_MODEL_REASONING": model_reasoning,
            "PI_API_PROTOCOL": api_protocol,
            "PI_PROXY_URL": proxy_url,
            "PI_PROXY_TOKEN": proxy_token,
            "PI_WORKSPACE_ROOT": str(durable_checkpoint_dir),
            "PI_SESSION_ID": session_id,
            "PI_AGENT_SESSION_ID": durable_session_id,
            "PI_RUNTIME_GENERATION": runtime_generation,
            "PI_CHECKPOINT_DIR": str(durable_checkpoint_dir),
            "PI_TOOL_GATEWAY_URL": tool_gateway_url,
            "PI_TOOL_GATEWAY_GRANT": tool_gateway_grant,
            "PI_TOOL_CATALOG_VERSION": tool_catalog_version,
        }
        if checkpoint_path is not None:
            bootstrap["PI_CHECKPOINT_PATH"] = str(checkpoint_path)
        elif legacy_messages:
            bootstrap["PI_LEGACY_MESSAGES"] = legacy_messages
        handle = PiRuntimeServiceHandle(
            service_url=self._service_url,
            control_token=self._control_token,
            bootstrap=bootstrap,
            on_stopped=self._unregister_service_session,
        )
        await handle.start()
        self._handles[session_id] = handle
        return handle

    def _unregister_service_session(self, session_id: str) -> None:
        self._handles.pop(session_id, None)


def get_pi_runtime_launcher(app: Any) -> PiRuntimeLauncher:
    """Lazily register the launcher on ``app.state``."""
    launcher = getattr(app.state, "pi_runtime_launcher", None)
    if launcher is None:
        from app.config import get_settings

        settings = get_settings()
        if settings.pi_runtime_service_url:
            if settings.pi_runtime_control_token is None:
                raise PiRuntimeError("Pi Runtime control token is not configured")
            launcher = PiRuntimeServiceLauncher(
                service_url=settings.pi_runtime_service_url,
                control_token=settings.pi_runtime_control_token.get_secret_value(),
            )
        else:
            # Local transport is retained only for focused development tests.
            # Deployed backend images contain no Node/Pi runtime and always set
            # PI_RUNTIME_SERVICE_URL to the isolated service.
            launcher = PiRuntimeLauncher()
        app.state.pi_runtime_launcher = launcher
    return launcher
