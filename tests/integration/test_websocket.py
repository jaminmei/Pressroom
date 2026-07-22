"""Integration tests for WebSocket endpoint and WSManager.

Covers:
- WSManager: connect, disconnect, publish, stale-client removal
- WebSocket endpoint: connected handshake, catch-up replay,
  control commands (pause/resume/cancel/cancel_node/retry_node),
  unknown command handling, disconnect cleanup
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.websocket import RunContext, WebSocketWorkspaceContext, active_runs
from app.api.websocket import router as ws_router
from app.main import app as main_app
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.task_run import TaskRun
from app.models.execution import ExecutionEvent, NodeOutput
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.ws_manager import WSManager, ws_manager
from tests._api_workspace_contract import TEST_USER_ID, TEST_WORKSPACE_ID
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI app with only the WebSocket router mounted."""
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
    """Ensure global state is clean before and after every test."""
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


def _insert_task_run(
    harness: WorkspaceApiHarness,
    *,
    task_id: str,
    workspace_id: str,
    status: str = "running",
) -> None:
    now = datetime.now(timezone.utc)
    with harness.session_factory() as session:
        session.add(
            TaskRun(
                id=task_id,
                status=status,
                workspace_id=workspace_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_websocket_enforced_rejects_unauthenticated(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client)
    _insert_task_run(
        workspace_api_harness,
        task_id="task_ws_unauth",
        workspace_id=workspace_id,
    )

    anonymous_client = TestClient(main_app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with anonymous_client.websocket_connect(
            f"/ws/workflow/task_ws_unauth?workspace_id={workspace_id}"
        ):
            pass

    assert exc_info.value.code == 1008


def test_websocket_enforced_scopes_run_to_active_workspace(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_a = create_workspace(owner.client, name="Workspace A")
    workspace_b = create_workspace(owner.client, name="Workspace B")
    _insert_task_run(
        workspace_api_harness,
        task_id="task_ws_cross",
        workspace_id=workspace_a,
    )

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with owner.client.websocket_connect(
            f"/ws/workflow/task_ws_cross?workspace_id={workspace_b}"
        ):
            pass

    assert exc_info.value.code == 1008


def test_websocket_enforced_viewer_can_read_but_not_cancel(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client)
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=viewer.user_id,
        role=WorkspaceRole.VIEWER.value,
    )
    _insert_task_run(
        workspace_api_harness,
        task_id="task_ws_viewer",
        workspace_id=workspace_id,
    )

    with viewer.client.websocket_connect(
        f"/ws/workflow/task_ws_viewer?workspace_id={workspace_id}"
    ) as ws:
        connected = ws.receive_json()
        assert connected["type"] == "connected"

        ws.send_json({"command": "cancel"})
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()

    assert exc_info.value.code == 1008


def test_websocket_enforced_runner_can_cancel(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    runner = workspace_api_harness.register_user("runner@example.com", "Runner")
    workspace_id = create_workspace(owner.client)
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=runner.user_id,
        role=WorkspaceRole.RUNNER.value,
    )
    _insert_task_run(
        workspace_api_harness,
        task_id="task_ws_runner",
        workspace_id=workspace_id,
    )

    with runner.client.websocket_connect(
        f"/ws/workflow/task_ws_runner?workspace_id={workspace_id}"
    ) as ws:
        connected = ws.receive_json()
        assert connected["type"] == "connected"

        ws.send_json({"command": "cancel"})
        message = ws.receive_json()

    assert message == {"type": "workflow_state", "data": {"status": "cancelled"}}


# ===================================================================
# TestWSManager — unit-level tests on the WSManager class
# ===================================================================


class TestWSManager:
    """Tests for the WSManager pub/sub singleton."""

    @pytest.mark.asyncio()
    async def test_connect_and_disconnect(self) -> None:
        manager = WSManager()
        ws = AsyncMock()

        await manager.connect("run-A", ws)
        assert "run-A" in manager.get_active_runs()

        await manager.disconnect("run-A", ws)
        assert "run-A" not in manager.get_active_runs()

    @pytest.mark.asyncio()
    async def test_publish_to_single_client(self) -> None:
        manager = WSManager()
        ws = AsyncMock()
        await manager.connect("run-A", ws)

        event = _make_event(output=NodeOutput(text="hello"))
        await manager.publish("run-A", event)

        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "node_event"
        assert payload["data"]["event_id"] == "evt-001"

    @pytest.mark.asyncio()
    async def test_publish_to_multiple_clients(self) -> None:
        manager = WSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect("run-A", ws1)
        await manager.connect("run-A", ws2)

        event = _make_event()
        await manager.publish("run-A", event)

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_publish_removes_stale_client(self) -> None:
        manager = WSManager()
        good_ws = AsyncMock()
        stale_ws = AsyncMock()
        stale_ws.send_json.side_effect = RuntimeError("connection lost")

        await manager.connect("run-A", good_ws)
        await manager.connect("run-A", stale_ws)

        event = _make_event()
        await manager.publish("run-A", event)

        # Stale client should be removed; good client still present
        assert "run-A" in manager._connections
        assert stale_ws not in manager._connections["run-A"]
        assert good_ws in manager._connections["run-A"]

    @pytest.mark.asyncio()
    async def test_disconnect_nonexistent_run(self) -> None:
        manager = WSManager()
        ws = AsyncMock()
        # Should not raise
        await manager.disconnect("ghost-run", ws)


# ===================================================================
# TestWebSocketEndpoint — integration tests via Starlette TestClient
# ===================================================================


class TestWebSocketEndpoint:
    """Tests for the WS /ws/workflow/{run_id} endpoint."""

    def test_connect_sends_connected(self, client: TestClient) -> None:
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "connected"
                assert msg["data"]["run_id"] == "run-1"

    @pytest.mark.parametrize(
        "status",
        ["completed", "partial_completed", "failed", "cancelled"],
    )
    def test_rbac_disabled_late_join_receives_terminal_snapshot(
        self,
        client: TestClient,
        status: str,
    ) -> None:
        repository = MagicMock()
        repository.get_snapshot_unchecked = AsyncMock(return_value=MagicMock(status=status))
        event_store = MagicMock()
        event_store.get_events.return_value = []

        with (
            patch("app.api.websocket.workspace_rbac_enforced", return_value=False),
            patch(
                "app.api.websocket._resolve_workspace_context",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.websocket.TaskRunRepository", return_value=repository),
            patch("app.api.websocket._get_event_store", return_value=event_store),
        ):
            with client.websocket_connect("/ws/workflow/run-terminal") as ws:
                message = ws.receive_json()

        assert message == {"type": "workflow_state", "data": {"status": status}}
        repository.get_snapshot_unchecked.assert_awaited_once_with("run-terminal")

    def test_catch_up_on_connect(self, client: TestClient) -> None:
        mock_event_1 = _make_event(event_id="evt-1", sequence=1, output=NodeOutput(text="first"))
        mock_event_2 = _make_event(event_id="evt-2", sequence=2, output=NodeOutput(text="second"))
        mock_store = MagicMock()
        mock_store.get_events_from.return_value = [mock_event_1, mock_event_2]

        with patch("app.api.websocket._get_event_store", return_value=mock_store):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.send_json({"command": "catch_up", "data": {"last_seq": 0}})

                # Should receive 2 replayed node_event messages, then connected
                replay_1 = ws.receive_json()
                assert replay_1["type"] == "node_event"
                assert replay_1["data"]["event_id"] == "evt-1"

                replay_2 = ws.receive_json()
                assert replay_2["type"] == "node_event"
                assert replay_2["data"]["event_id"] == "evt-2"

                connected_msg = ws.receive_json()
                assert connected_msg["type"] == "connected"

                mock_store.get_events_from.assert_called_once_with("run-1", 0)

    def test_catch_up_no_data(self, client: TestClient) -> None:
        """When no initial message is sent (timeout), just get connected."""
        mock_store = MagicMock()
        with patch("app.api.websocket._get_event_store", return_value=mock_store):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                # Don't send any command — the endpoint will timeout on
                # receive_json and fall through to sending connected.
                msg = ws.receive_json()
                assert msg["type"] == "connected"
                assert msg["data"]["run_id"] == "run-1"
                # EventStore should NOT have been called
                mock_store.get_events_from.assert_not_called()

    def test_pause_command(self, client: TestClient) -> None:
        # Set up an active RunContext for the run
        mock_task = MagicMock(spec=asyncio.Task)
        ctx = RunContext(task=mock_task)
        active_runs["run-1"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                # Consume the connected message
                ws.receive_json()

                ws.send_json({"command": "pause"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "paused"

                # Verify pause_event is set (wait returns immediately)
                assert ctx.pause_event.is_set()

    def test_resume_command(self, client: TestClient) -> None:
        # Set up a paused RunContext
        mock_task = MagicMock(spec=asyncio.Task)
        ctx = RunContext(task=mock_task)
        ctx.pause_event.set()  # start paused
        active_runs["run-1"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected

                ws.send_json({"command": "resume"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "running"

                # Verify pause_event is cleared (wait blocks = running)
                assert not ctx.pause_event.is_set()

    def test_cancel_command(self, client: TestClient) -> None:
        mock_task = MagicMock(spec=asyncio.Task)
        ctx = RunContext(task=mock_task)
        active_runs["run-1"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected

                ws.send_json({"command": "cancel"})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "cancelled"

                mock_task.cancel.assert_called_once()

    def test_cancel_node_command(self, client: TestClient) -> None:
        mock_task = MagicMock(spec=asyncio.Task)
        ctx = RunContext(task=mock_task)
        active_runs["run-1"] = ctx

        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected

                ws.send_json({"command": "cancel_node", "data": {"node_id": "ocr-1"}})
                msg = ws.receive_json()
                assert msg["type"] == "workflow_state"
                assert msg["data"]["status"] == "node_cancelled"
                assert msg["data"]["node_id"] == "ocr-1"

                # Verify node added to cancelled set
                assert "ocr-1" in ctx.cancelled_nodes

    def test_retry_node_is_unsupported(self, client: TestClient) -> None:
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected

                ws.send_json({"command": "retry_node", "data": {"node_id": "ocr-1"}})
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert msg["data"]["code"] == "UNSUPPORTED_COMMAND"

    def test_unknown_command(self, client: TestClient) -> None:
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected

                ws.send_json({"command": "do_something_weird"})
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert msg["data"]["code"] == "UNKNOWN_COMMAND"
                assert "do_something_weird" in msg["data"]["message"]

    def test_disconnect_cleanup(self, client: TestClient) -> None:
        """After a client disconnects, WSManager should no longer track the run."""
        with patch("app.api.websocket._get_event_store"):
            with client.websocket_connect("/ws/workflow/run-1") as ws:
                ws.receive_json()  # consume connected
                # While connected, the run should be tracked
                assert "run-1" in ws_manager.get_active_runs()
            # After the context manager exits (client disconnects),
            # cleanup should remove the run
            assert "run-1" not in ws_manager.get_active_runs()
