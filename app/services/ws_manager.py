"""WebSocket connection manager — pub/sub keyed by workflow run_id."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from app.models.execution import ExecutionEvent

logger = logging.getLogger(__name__)


class WSManager:
    """Manages WebSocket connections per workflow run_id.

    Provides:
    - ``connect(run_id, websocket)``: register a WebSocket connection
    - ``disconnect(run_id, websocket)``: unregister
    - ``publish(run_id, event)``: fan-out ExecutionEvent to all connected clients
    - ``get_active_runs()``: list run_ids with active connections
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        """Register a WebSocket for the given run_id."""
        async with self._lock:
            self._connections.setdefault(run_id, set()).add(websocket)
        logger.debug(
            "WS connected for run %s (%d clients)",
            run_id,
            len(self._connections.get(run_id, set())),
        )

    async def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket from the given run_id."""
        async with self._lock:
            conns = self._connections.get(run_id)
            if conns is None:
                return
            conns.discard(websocket)
            if not conns:
                del self._connections[run_id]
        logger.debug("WS disconnected for run %s", run_id)

    async def close_policy_violation(self, run_id: str, websocket: WebSocket) -> None:
        try:
            await websocket.close(code=1008)
        finally:
            await self.disconnect(run_id, websocket)

    async def publish(self, run_id: str, event: ExecutionEvent) -> None:
        """Serialize and fan-out an ExecutionEvent to all connected clients.

        If sending to a client fails (disconnected), that client is silently
        removed from the connection set.
        """
        async with self._lock:
            conns = self._connections.get(run_id)
            if not conns:
                return
            # Snapshot to avoid mutating while iterating
            to_remove: list[WebSocket] = []
            payload = {"type": "node_event", "data": event.model_dump(mode="json")}

            for ws in list(conns):
                try:
                    await ws.send_json(payload)
                except Exception:
                    logger.debug("Removing stale WS client for run %s", run_id)
                    to_remove.append(ws)

            for ws in to_remove:
                conns.discard(ws)
                if not conns:
                    del self._connections[run_id]

    def get_active_runs(self) -> list[str]:
        """Return run_ids that currently have at least one connected client."""
        return list(self._connections.keys())

    async def send_workflow_state(self, run_id: str, status: str) -> None:
        """Send a workflow_state message to all connected clients for a run."""
        async with self._lock:
            conns = self._connections.get(run_id)
            if not conns:
                return
            payload = {"type": "workflow_state", "data": {"status": status}}
            to_remove: list[WebSocket] = []
            for ws in list(conns):
                try:
                    await ws.send_json(payload)
                except Exception:
                    to_remove.append(ws)
            for ws in to_remove:
                conns.discard(ws)
                if not conns:
                    del self._connections[run_id]


# Module-level singleton.
ws_manager = WSManager()
