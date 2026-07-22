"""WebSocket endpoint for real-time workflow execution monitoring.

Route: ``WS /ws/workflow/{run_id}``

Server-to-client messages all follow the envelope::

    { "type": "<msg_type>", "data": { ... } }

Message types:
  - ``connected``  — sent after accept + optional catch-up
  - ``node_event``  — forwarded ExecutionEvent
  - ``workflow_state``  — state snapshot after events or control commands
  - ``error``  — error responses

Client-to-server commands::

    { "command": "<cmd>", "data": { ... } }

Commands:
  - ``catch_up``     — replay missed events since ``last_seq``
  - ``pause``        — pause workflow (running nodes finish, no new dispatch)
  - ``resume``       — resume paused workflow
  - ``cancel``       — cancel workflow entirely
  - ``retry_node``   — returns an unsupported-command error
  - ``cancel_node``  — cancel a specific running node
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import get_auth_service
from app.config import get_settings
from app.db.session import SessionLocal
from app.errors import AppError
from app.models.auth import AuthenticatedContext
from app.models.db.workspace_member import WorkspaceMember
from app.repositories.task_run_repository import TaskRunRepository
from app.services.event_store import EventStore
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.workspace_rbac import workspace_rbac_enforced
from app.services.workspace_resolver import resolve_default_workspace
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()
WORKSPACE_WS_REVALIDATE_SECONDS = float(os.getenv("WORKSPACE_WS_REVALIDATE_SECONDS", "15"))


# ---------------------------------------------------------------------------
# Run context — tracks an in-progress DAG execution for control commands
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    """Handles the async Task and control primitives for a running workflow."""

    task: asyncio.Task[Any]
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled_nodes: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # pause_event is *set* when paused (.wait() returns immediately),
        # *cleared* when running (.wait() blocks).  Start in running state.
        if self.pause_event.is_set():
            self.pause_event.clear()


active_runs: dict[str, RunContext] = {}


@dataclass(frozen=True, slots=True)
class WebSocketWorkspaceContext:
    auth: AuthenticatedContext
    workspace_id: str
    role: WorkspaceRole
    capabilities: frozenset[str]


# ---------------------------------------------------------------------------
# Helper: obtain an EventStore instance
# ---------------------------------------------------------------------------


def _get_event_store() -> EventStore:
    """Create an EventStore using the default session factory."""
    return EventStore()


async def _close_policy_violation(websocket: WebSocket) -> None:
    try:
        await websocket.close(code=1008)
    except RuntimeError:
        pass


def _requested_workspace_id(
    websocket: WebSocket,
    context: AuthenticatedContext,
) -> str | None:
    return (
        websocket.query_params.get("workspace_id")
        or websocket.headers.get("X-Workspace-Id")
        or context.workspace_id
    )


async def _run_visible_in_workspace(run_id: str, workspace_id: str, websocket: WebSocket) -> bool:
    running_tasks: dict[str, Any] = getattr(websocket.app.state, "running_tasks", {})
    running_context = running_tasks.get(run_id)
    if running_context is not None:
        return getattr(running_context, "workspace_id", None) == workspace_id

    snapshot = await TaskRunRepository().get_snapshot(run_id, workspace_id=workspace_id)
    return snapshot is not None


async def _resolve_workspace_context(
    websocket: WebSocket,
    run_id: str,
) -> WebSocketWorkspaceContext | None:
    if not workspace_rbac_enforced():
        return None

    raw_session_token = websocket.cookies.get(get_settings().auth_session_cookie_name)
    try:
        auth_context = get_auth_service().require_authenticated(raw_session_token)
    except AppError:
        await _close_policy_violation(websocket)
        return None

    with SessionLocal() as session:
        workspace_id = _requested_workspace_id(websocket, auth_context)
        if workspace_id is None:
            workspace_id = resolve_default_workspace(session, auth_context.user.id)

        member = (
            session.query(WorkspaceMember)
            .filter_by(
                workspace_id=workspace_id,
                user_id=auth_context.user.id,
            )
            .one_or_none()
        )

    if member is None:
        await _close_policy_violation(websocket)
        return None

    role = WorkspaceRole(member.role)
    capabilities = CAPABILITIES[role]
    if "run.view" not in capabilities:
        await _close_policy_violation(websocket)
        return None

    try:
        if not await _run_visible_in_workspace(run_id, workspace_id, websocket):
            await _close_policy_violation(websocket)
            return None
    except Exception as exc:
        logger.warning(
            "Failed to resolve websocket run scope for %s error_type=%s",
            run_id,
            type(exc).__name__,
        )
        await _close_policy_violation(websocket)
        return None

    return WebSocketWorkspaceContext(
        auth=auth_context,
        workspace_id=workspace_id,
        role=role,
        capabilities=capabilities,
    )


async def _authorize_control_command(
    websocket: WebSocket,
    context: WebSocketWorkspaceContext | None,
    run_id: str,
) -> bool:
    if context is None:
        return True
    fresh_context = await _resolve_workspace_context(websocket, run_id)
    if fresh_context is not None and "run.cancel" in fresh_context.capabilities:
        return True
    await _close_policy_violation(websocket)
    return False


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/workflow/{run_id}")
async def workflow_websocket(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for monitoring / controlling a workflow run."""
    workspace_context = await _resolve_workspace_context(websocket, run_id)
    if workspace_rbac_enforced() and workspace_context is None:
        return

    await websocket.accept()
    logger.info("WebSocket accepted for run_id=%s", run_id)

    # -- 1. Register with WSManager immediately --------------------------------
    await ws_manager.connect(run_id, websocket)
    connected = True

    try:
        init_msg: dict[str, Any] | None = None
        try:
            received = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
            init_msg = received if isinstance(received, dict) else None
        except asyncio.TimeoutError:
            init_msg = None
        except WebSocketDisconnect:
            return
        except Exception as exc:
            logger.warning(
                "Error during initial websocket receive for run %s error_type=%s",
                run_id,
                type(exc).__name__,
            )

        # -- 1b. Check if task already completed before WS connected -----------
        try:
            repo = TaskRunRepository()
            ws_workspace_id = workspace_context.workspace_id if workspace_context else None
            if ws_workspace_id is not None:
                snapshot = await repo.get_snapshot(run_id, workspace_id=ws_workspace_id)
            else:
                snapshot = await repo.get_snapshot_unchecked(run_id)
            if snapshot is not None and snapshot.status in (
                "completed",
                "partial_completed",
                "failed",
                "cancelled",
            ):
                # Replay all missed node events so the frontend can update
                # individual node statuses before receiving the terminal state.
                try:
                    event_store = _get_event_store()
                    missed_events = event_store.get_events(run_id)
                    for event in missed_events:
                        await websocket.send_json(
                            {"type": "node_event", "data": event.model_dump(mode="json")}
                        )
                    if missed_events:
                        logger.info(
                            "Replayed %d events for late-join run %s",
                            len(missed_events),
                            run_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to replay events for late-join run %s error_type=%s",
                        run_id,
                        type(exc).__name__,
                    )

                await websocket.send_json(
                    {"type": "workflow_state", "data": {"status": snapshot.status}}
                )
                logger.info(
                    "Sent late workflow_state for completed run %s: %s",
                    run_id,
                    snapshot.status,
                )
                return
        except Exception as exc:
            logger.warning(
                "Failed to check snapshot status for run %s error_type=%s",
                run_id,
                type(exc).__name__,
            )

        # -- 2. Optional catch-up ----------------------------------------------
        if (
            init_msg is not None
            and init_msg.get("command") == "catch_up"
            and isinstance(init_msg.get("data"), dict)
            and "last_seq" in init_msg["data"]
        ):
            try:
                last_seq = int(init_msg["data"]["last_seq"])
                event_store = _get_event_store()
                missed = event_store.get_events_from(run_id, last_seq)
                for event in missed:
                    await websocket.send_json(
                        {"type": "node_event", "data": event.model_dump(mode="json")}
                    )
                init_msg = None
            except Exception as exc:
                logger.warning(
                    "Error during catch-up for run %s error_type=%s",
                    run_id,
                    type(exc).__name__,
                )

        await websocket.send_json({"type": "connected", "data": {"run_id": run_id}})

        # -- 3. Command loop ---------------------------------------------------
        pending_msg = init_msg
        next_revalidation = asyncio.get_running_loop().time() + WORKSPACE_WS_REVALIDATE_SECONDS
        while True:
            if pending_msg is not None:
                msg = pending_msg
            else:
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=max(next_revalidation - asyncio.get_running_loop().time(), 0),
                    )
                except asyncio.TimeoutError:
                    fresh_context = await _resolve_workspace_context(websocket, run_id)
                    if workspace_context is not None and fresh_context is None:
                        return
                    workspace_context = fresh_context
                    await websocket.send_json({"type": "ping", "data": {}})
                    next_revalidation = (
                        asyncio.get_running_loop().time() + WORKSPACE_WS_REVALIDATE_SECONDS
                    )
                    continue
            pending_msg = None
            command = msg.get("command") if isinstance(msg, dict) else None

            if command == "pause":
                if not await _authorize_control_command(websocket, workspace_context, run_id):
                    return
                ctx = active_runs.get(run_id)
                if ctx:
                    ctx.pause_event.set()
                await websocket.send_json({"type": "workflow_state", "data": {"status": "paused"}})

            elif command == "resume":
                if not await _authorize_control_command(websocket, workspace_context, run_id):
                    return
                ctx = active_runs.get(run_id)
                if ctx:
                    ctx.pause_event.clear()
                await websocket.send_json({"type": "workflow_state", "data": {"status": "running"}})

            elif command == "cancel":
                if not await _authorize_control_command(websocket, workspace_context, run_id):
                    return
                ctx = active_runs.get(run_id)
                if ctx:
                    ctx.task.cancel()
                await websocket.send_json(
                    {"type": "workflow_state", "data": {"status": "cancelled"}}
                )

            elif command == "retry_node":
                if not await _authorize_control_command(websocket, workspace_context, run_id):
                    return
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "UNSUPPORTED_COMMAND",
                            "message": "retry_node is not supported",
                        },
                    }
                )

            elif command == "cancel_node":
                if not await _authorize_control_command(websocket, workspace_context, run_id):
                    return
                node_id = (
                    msg.get("data", {}).get("node_id")
                    if isinstance(msg.get("data"), dict)
                    else None
                )
                ctx = active_runs.get(run_id)
                if ctx and node_id:
                    ctx.cancelled_nodes.add(node_id)
                await websocket.send_json(
                    {
                        "type": "workflow_state",
                        "data": {"status": "node_cancelled", "node_id": node_id},
                    }
                )

            elif command == "pong":
                await websocket.send_json({"type": "pong", "data": {}})

            elif command == "catch_up":
                # Late catch-up request (not just at connect time)
                data = msg.get("data") if isinstance(msg, dict) else None
                if isinstance(data, dict) and "last_seq" in data:
                    event_store = _get_event_store()
                    missed = event_store.get_events_from(run_id, int(data["last_seq"]))
                    for event in missed:
                        await websocket.send_json(
                            {
                                "type": "node_event",
                                "data": event.model_dump(mode="json"),
                            }
                        )

            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "UNKNOWN_COMMAND",
                            "message": f"Unknown command: {command!r}",
                        },
                    }
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for run_id=%s", run_id)
    except Exception as exc:
        logger.error(
            "WebSocket error for run_id=%s error_type=%s",
            run_id,
            type(exc).__name__,
        )
    finally:
        if connected:
            await ws_manager.disconnect(run_id, websocket)
