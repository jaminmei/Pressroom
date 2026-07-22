"""Integration tests for WebSocket lifecycle — control commands, reconnect
catch-up, and event replay.

Tasks 11.5–11.7 from the doctags-removal-flatten-json change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient

from app.api.websocket import RunContext, WebSocketWorkspaceContext, active_runs
from app.api.websocket import router as ws_router
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import ExecutionEvent, NodeOutput
from app.services.event_store import EventStore
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.ws_manager import ws_manager
from tests._api_workspace_contract import TEST_USER_ID, TEST_WORKSPACE_ID

SessionFactory = Callable[[], Session]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_router)
    return app


@pytest.fixture()
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    role = WorkspaceRole.OWNER
    auth = AuthenticatedContext(
        user=AuthUser(id=TEST_USER_ID, email="unit-api@example.com", name="Unit API"),
        session=AuthSessionInfo(
            id="as_unit_api",
            user_id=TEST_USER_ID,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id=TEST_WORKSPACE_ID,
        role=role,
        capabilities=CAPABILITIES[role],
    )
    workspace_context = WebSocketWorkspaceContext(
        auth=auth,
        workspace_id=TEST_WORKSPACE_ID,
        role=role,
        capabilities=CAPABILITIES[role],
    )

    async def resolve_workspace_context(
        _websocket: object,
        _run_id: str,
    ) -> WebSocketWorkspaceContext:
        return workspace_context

    monkeypatch.setattr(
        "app.api.websocket._resolve_workspace_context",
        resolve_workspace_context,
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup() -> None:
    active_runs.clear()
    ws_manager._connections.clear()
    yield
    active_runs.clear()
    ws_manager._connections.clear()


def _make_event(
    *,
    event_id: str = "evt-001",
    run_id: str = "run-1",
    node_id: str = "node-1",
    node_type: str = "engine/ocr",
    event_type: str = "completed",
    sequence: int = 1,
    timestamp: float = 1713945600.0,
    output: NodeOutput | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        workflow_run_id=run_id,
        node_id=node_id,
        node_type=node_type,
        event_type=event_type,
        sequence=sequence,
        timestamp=timestamp,
        output=output,
    )


@pytest.fixture()
def event_store(tmp_path) -> Iterator[tuple[EventStore, SessionFactory]]:
    db_path = tmp_path / "ws_lifecycle.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    metadata = MetaData()
    ExecutionEventRecord.__table__.to_metadata(metadata)
    with engine.begin() as conn:
        metadata.create_all(conn)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventStore(session_factory=session_factory), session_factory
    engine.dispose()


def _make_ctx() -> tuple[MagicMock, RunContext]:
    mock_task = MagicMock(spec=asyncio.Task)
    ctx = RunContext(task=mock_task)
    return mock_task, ctx


# ---------------------------------------------------------------------------
# 11.5 WebSocket control commands
# ---------------------------------------------------------------------------


class TestControlCommands:
    """Extended tests for pause/resume/cancel/cancel_node commands."""

    def test_pause_sets_event(self, client: TestClient) -> None:
        _, ctx = _make_ctx()
        active_runs["run-ctrl"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-ctrl") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "pause"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "paused"
                assert ctx.pause_event.is_set()

    def test_resume_clears_event(self, client: TestClient) -> None:
        _, ctx = _make_ctx()
        ctx.pause_event.set()
        active_runs["run-ctrl"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-ctrl") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "resume"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "running"
                assert not ctx.pause_event.is_set()

    def test_pause_resume_cycle(self, client: TestClient) -> None:
        """Multiple pause/resume cycles should toggle correctly."""
        _, ctx = _make_ctx()
        active_runs["run-cycle"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-cycle") as ws:
                ws.receive_json()  # connected

                # First pause
                ws.send_json({"command": "pause"})
                ws.receive_json()
                assert ctx.pause_event.is_set()

                # Resume
                ws.send_json({"command": "resume"})
                ws.receive_json()
                assert not ctx.pause_event.is_set()

                # Second pause
                ws.send_json({"command": "pause"})
                ws.receive_json()
                assert ctx.pause_event.is_set()

                # Second resume
                ws.send_json({"command": "resume"})
                ws.receive_json()
                assert not ctx.pause_event.is_set()

    def test_cancel_invokes_task_cancel(self, client: TestClient) -> None:
        mock_task, ctx = _make_ctx()
        active_runs["run-cancel"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-cancel") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "cancel"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "cancelled"
                mock_task.cancel.assert_called_once()

    def test_cancel_without_active_run(self, client: TestClient) -> None:
        """Cancel on non-existent run should still respond (no crash)."""
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-noexist") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "cancel"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "cancelled"

    def test_cancel_multiple_nodes(self, client: TestClient) -> None:
        """Cancel several specific nodes."""
        _, ctx = _make_ctx()
        active_runs["run-multicancel"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-multicancel") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "cancel_node", "data": {"node_id": "ocr-1"}})
                ws.receive_json()

                ws.send_json({"command": "cancel_node", "data": {"node_id": "model-2"}})
                ws.receive_json()

                ws.send_json({"command": "cancel_node", "data": {"node_id": "pre-3"}})
                ws.receive_json()

                assert ctx.cancelled_nodes == {"ocr-1", "model-2", "pre-3"}

    def test_retry_node_returns_unsupported_with_context(self, client: TestClient) -> None:
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-retry") as ws:
                ws.receive_json()  # connected

                ws.send_json({"command": "retry_node", "data": {"node_id": "ocr-x"}})
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert msg["data"]["code"] == "UNSUPPORTED_COMMAND"


# ---------------------------------------------------------------------------
# 11.6 Reconnect with sequence-based catch-up
# ---------------------------------------------------------------------------


class TestReconnectCatchUp:
    """Client disconnects, reconnects, and receives only missed events."""

    def test_catch_up_on_reconnect(self, client: TestClient) -> None:
        """First session gets events 1-2, second session gets only event 3."""
        mock_store = MagicMock()

        # Return events 1-2 for initial connection (last_seq=0)
        evt1 = _make_event(event_id="evt-1", sequence=1, output=NodeOutput(text="first"))
        evt2 = _make_event(event_id="evt-2", sequence=2, output=NodeOutput(text="second"))
        evt3 = _make_event(event_id="evt-3", sequence=3, output=NodeOutput(text="third"))

        # Session 1: catch_up with last_seq=0 returns all 3
        # Session 2: catch_up with last_seq=2 returns only evt3
        mock_store.get_events_from.side_effect = [
            [evt1, evt2],  # first connection: events > 0 → evt1, evt2
            [evt3],  # second connection: events > 2 → evt3
        ]

        with patch("app.api.websocket._get_event_store", return_value=mock_store):
            # Session 1
            with client.websocket_connect("/ws/workflow/run-reconnect") as ws:
                ws.send_json({"command": "catch_up", "data": {"last_seq": 0}})
                # Receive 2 replayed events
                r1 = ws.receive_json()
                assert r1["type"] == "node_event"
                assert r1["data"]["event_id"] == "evt-1"
                r2 = ws.receive_json()
                assert r2["type"] == "node_event"
                assert r2["data"]["event_id"] == "evt-2"
                # Connected ack
                r3 = ws.receive_json()
                assert r3["type"] == "connected"

            # Session 2 — reconnect with last_seq=2
            with client.websocket_connect("/ws/workflow/run-reconnect") as ws:
                ws.send_json({"command": "catch_up", "data": {"last_seq": 2}})
                r4 = ws.receive_json()
                assert r4["type"] == "node_event"
                assert r4["data"]["event_id"] == "evt-3"
                # No evt-1 or evt-2 replayed
                r5 = ws.receive_json()
                assert r5["type"] == "connected"

    def test_late_catch_up_command(self, client: TestClient) -> None:
        """Client sends catch_up after the initial handshake."""
        mock_store = MagicMock()
        evt_late = _make_event(event_id="evt-late", sequence=5, output=NodeOutput(text="late"))
        mock_store.get_events_from.return_value = [evt_late]

        with patch("app.api.websocket._get_event_store", return_value=mock_store):
            with client.websocket_connect("/ws/workflow/run-late") as ws:
                # Don't send catch_up initially — just get connected
                msg = ws.receive_json()
                assert msg["type"] == "connected"

                # Now send late catch_up
                ws.send_json({"command": "catch_up", "data": {"last_seq": 4}})
                replayed = ws.receive_json()
                assert replayed["type"] == "node_event"
                assert replayed["data"]["event_id"] == "evt-late"

    def test_no_events_to_catch_up(self, client: TestClient) -> None:
        """Catch-up with no new events returns nothing extra."""
        mock_store = MagicMock()
        mock_store.get_events_from.return_value = []

        with patch("app.api.websocket._get_event_store", return_value=mock_store):
            with client.websocket_connect("/ws/workflow/run-empty") as ws:
                ws.send_json({"command": "catch_up", "data": {"last_seq": 10}})
                # No events replayed — go straight to connected
                msg = ws.receive_json()
                assert msg["type"] == "connected"


# ---------------------------------------------------------------------------
# 11.7 Event replay to arbitrary sequence number
# ---------------------------------------------------------------------------


class TestEventReplay:
    """Test EventStore.replay_to() with real SQLite database."""

    def test_replay_to_partial_sequence(self, event_store) -> None:
        es, _ = event_store
        run_id = "replay-test"

        # Append 5 events for different nodes
        for i in range(1, 6):
            es.append(
                _make_event(
                    event_id=f"evt-{i}",
                    run_id=run_id,
                    node_id=f"node-{i}",
                    event_type="completed",
                    sequence=i,
                    output=NodeOutput(text=f"output-{i}"),
                )
            )

        # compute_state should have all 5
        full_state = es.compute_state(run_id)
        assert len(full_state) == 5

        # replay_to(3) should only have outputs from events 1-3
        partial_state = es.replay_to(run_id, sequence=3)
        assert len(partial_state) == 3
        for i in range(1, 4):
            assert f"node-{i}" in partial_state
            assert partial_state[f"node-{i}"].text == f"output-{i}"

        # Events 4-5 should NOT be in partial state
        assert "node-4" not in partial_state
        assert "node-5" not in partial_state

    def test_replay_to_sequence_zero(self, event_store) -> None:
        es, _ = event_store
        run_id = "replay-zero"

        es.append(
            _make_event(
                event_id="evt-1",
                run_id=run_id,
                node_id="node-1",
                event_type="completed",
                sequence=1,
                output=NodeOutput(text="only"),
            )
        )

        # replay_to(0) should include nothing (sequence <= 0 matches nothing)
        state = es.replay_to(run_id, sequence=0)
        assert len(state) == 0

    def test_replay_to_full_sequence(self, event_store) -> None:
        es, _ = event_store
        run_id = "replay-full"

        for i in range(1, 4):
            es.append(
                _make_event(
                    event_id=f"evt-{i}",
                    run_id=run_id,
                    node_id=f"node-{i}",
                    event_type="completed",
                    sequence=i,
                    output=NodeOutput(text=f"out-{i}"),
                )
            )

        # replay_to(3) should be same as compute_state
        replayed = es.replay_to(run_id, sequence=3)
        full = es.compute_state(run_id)
        assert len(replayed) == len(full) == 3

    def test_replay_ignores_non_completed_events(self, event_store) -> None:
        es, _ = event_store
        run_id = "replay-noncomp"

        es.append(
            _make_event(
                event_id="evt-start",
                run_id=run_id,
                node_id="node-1",
                event_type="started",
                sequence=1,
            )
        )
        es.append(
            _make_event(
                event_id="evt-comp",
                run_id=run_id,
                node_id="node-1",
                event_type="completed",
                sequence=2,
                output=NodeOutput(text="done"),
            )
        )
        es.append(
            _make_event(
                event_id="evt-fail",
                run_id=run_id,
                node_id="node-2",
                event_type="failed",
                sequence=3,
            )
        )

        state = es.replay_to(run_id, sequence=3)
        # Only the "completed" event contributes
        assert len(state) == 1
        assert "node-1" in state
        assert state["node-1"].text == "done"

    def test_replay_last_completed_wins(self, event_store) -> None:
        es, _ = event_store
        run_id = "replay-wins"

        # Two completed events for same node (retry scenario)
        es.append(
            _make_event(
                event_id="evt-1",
                run_id=run_id,
                node_id="node-1",
                event_type="completed",
                sequence=1,
                output=NodeOutput(text="first"),
            )
        )
        es.append(
            _make_event(
                event_id="evt-2",
                run_id=run_id,
                node_id="node-1",
                event_type="completed",
                sequence=2,
                output=NodeOutput(text="second"),
            )
        )

        state = es.replay_to(run_id, sequence=2)
        assert len(state) == 1
        assert state["node-1"].text == "second"
