from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.services.chatbox_broker as chatbox_broker_module
from app.api.auth import get_authenticated_context
from app.api.chatbox import (
    _claim_runtime_for_session,
    _get_session,
    _release_websocket_session,
    _runtime_for_session,
    _runtime_lock,
    _stop_session_runtime,
    chatbox_websocket,
    router,
)
from app.api.internal_proxy import issue_internal_proxy_grant
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.errors import AppError, ErrorCode
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.chatbox_session import ChatboxSession
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ApiProtocol, ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from app.services.chatbox_broker import ChatboxBrokerResyncError, ChatboxRuntimeBroker
from app.services.chatbox_history import ChatboxHistory
from app.services.pi_runtime import PiRuntimeError, PiRuntimeHandle, PiRuntimeLauncher


class FakeRuntime:
    def __init__(self) -> None:
        self.session_id = "pi-session"
        self.state = "running"
        self.commands: list[dict[str, object]] = []
        self.stopped = False
        self.runtime_generation = 1
        self.checkpoint_path = Path(tempfile.gettempdir()) / f"fake-pi-{id(self)}.jsonl"
        self.checkpoint_path.write_text('{"type":"session"}\n', encoding="utf-8")
        self.checkpoint_schema_version = 3

    async def send_command(self, command: dict[str, object]) -> None:
        self.commands.append(command)

    async def events(self) -> AsyncIterator[dict[str, object]]:
        yield {"type": "agent_start"}
        yield {
            "type": "message_update",
            "message": {"role": "assistant", "content": "private cumulative transcript"},
            "assistantMessageEvent": {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": "visible",
            },
            "token": "secret",
        }
        yield {"type": "custom_message", "display": False, "text": "hidden"}
        await asyncio.Event().wait()

    async def stop(self) -> None:
        self.stopped = True
        self.state = "stopped"


class FakeLauncher:
    def __init__(self) -> None:
        self.runtime = FakeRuntime()
        self.start_kwargs: dict[str, object] = {}
        self.start_count = 0

    async def start_session(self, *_args: object, **kwargs: object) -> FakeRuntime:
        self.start_count += 1
        self.start_kwargs = kwargs
        checkpoint_dir = Path(str(kwargs["checkpoint_dir"]))
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = kwargs.get("checkpoint_path")
        self.runtime.checkpoint_path = (
            Path(str(checkpoint_path))
            if checkpoint_path is not None
            else checkpoint_dir / "session.jsonl"
        )
        if not self.runtime.checkpoint_path.exists():
            self.runtime.checkpoint_path.write_text('{"type":"session"}\n', encoding="utf-8")
        self.runtime.runtime_generation = int(kwargs["runtime_generation"])
        await asyncio.sleep(0)
        return self.runtime

    async def stop_session(self, session_id: str) -> None:
        assert session_id == self.runtime.session_id
        await self.runtime.stop()


def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _expect_runtime_restoring(ws: object) -> dict[str, object]:
    event = ws.receive_json()  # type: ignore[attr-defined]
    assert event["type"] == "runtime_status"
    assert event["status"] == "restoring"
    assert isinstance(event["runtime_generation"], int)
    return event


def _expect_runtime_ready(ws: object) -> None:
    restoring = _expect_runtime_restoring(ws)
    ready = ws.receive_json()  # type: ignore[attr-defined]
    assert ready["type"] == "runtime_status"
    assert ready["status"] == "ready"
    assert ready["runtime_generation"] == restoring["runtime_generation"]
    assert isinstance(ready["restore_duration_ms"], float)


@dataclass(frozen=True, slots=True)
class ChatboxTestClient:
    client: TestClient
    store: ProviderStore


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatboxTestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_SESSION_SECRET", "chatbox-agent-session-test-secret")
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as database:
        database.add_all(
            [
                UserAccount(id="user-a", email="a@example.test", password_hash="hash", name="A"),
                Workspace(
                    id="workspace-a",
                    name="A",
                    slug=None,
                    description=None,
                    owner_user_id="user-a",
                ),
                WorkspaceMember(
                    id="member-a",
                    workspace_id="workspace-a",
                    user_id="user-a",
                    role="owner",
                ),
            ]
        )
        database.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_authenticated_context] = lambda: AuthenticatedContext(
        user=AuthUser(id="user-a", email="a@example.test"),
        session=AuthSessionInfo(
            id="auth-a", user_id="user-a", expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc)
        ),
        workspace_id="workspace-a",
    )
    store = ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    app.state.provider_store = store

    async def allow_admission(**_kwargs: object) -> str:
        return "allow_platform_turn"

    app.state.agent_admission_classifier = allow_admission
    with TestClient(app) as test_client:
        try:
            yield ChatboxTestClient(client=test_client, store=store)
        finally:
            get_settings.cache_clear()


def _create_default_provider(store: ProviderStore) -> str:
    provider = store.create_provider(
        ModelProviderCreate(
            name="Chat",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="test-model",
            is_chatbot_default=True,
            scope=ProviderScope.workspace,
            workspace_id="workspace-a",
        )
    )
    return provider.id


def test_post_creates_session_for_default_provider(client: ChatboxTestClient) -> None:
    provider_id = _create_default_provider(client.store)
    response = client.client.post("/api/chatbox/sessions")
    assert response.status_code == 201
    payload = response.json()
    assert str(UUID(payload["session_id"])) == payload["session_id"]
    assert payload["state"] == "idle"
    assert payload["provider_id"] == provider_id
    assert payload["model_id"] == "test-model"
    assert payload["messages"] == []
    assert payload["tool_executions"] == {}
    assert payload["compaction_notes"] == []
    assert payload["live_message_id"] is None
    assert payload["snapshot_revision"] == 0
    assert payload["session_state"] == "active"
    assert payload["runtime_state"] == "stopped"
    assert payload["runtime_generation"] == 1
    assert payload["is_current"] is True


def test_post_returns_conflict_without_default_provider(client: ChatboxTestClient) -> None:
    response = client.client.post("/api/chatbox/sessions")
    assert response.status_code == 409
    assert response.json()["detail"] == "No workspace chatbot default provider configured"


def test_get_returns_authoritative_state_and_empty_history(client: ChatboxTestClient) -> None:
    _create_default_provider(client.store)
    created = client.client.post("/api/chatbox/sessions").json()
    response = client.client.get(f"/api/chatbox/sessions/{created['session_id']}")
    assert response.status_code == 200
    assert response.json()["messages"] == []
    assert response.json()["state"] == "idle"


def test_websocket_persists_projected_history_before_reconnect(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HistoryRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            yield {"type": "message_start", "message": {"role": "user", "content": "Hi"}}
            yield {"type": "message_end", "message": {"role": "user", "content": "Hi"}}
            yield {"type": "message_start", "message": {"role": "assistant", "content": []}}
            yield {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "contentIndex": 0,
                    "delta": "Hello",
                },
            }
            yield {
                "type": "tool_execution_start",
                "toolCallId": "tool-1",
                "toolName": "read",
                "args": {"path": "README.md"},
            }
            yield {
                "type": "tool_execution_end",
                "toolCallId": "tool-1",
                "toolName": "read",
                "result": {"content": [{"type": "text", "text": "done"}]},
                "isError": False,
            }
            yield {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }
            yield {"type": "agent_settled"}
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = HistoryRuntime()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    received: list[dict[str, object]] = []
    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        while True:
            event = ws.receive_json()
            received.append(event)
            if event["type"] == "agent_settled":
                break

    message_events = [event for event in received if event["type"].startswith("message_")]
    user_start, user_end = message_events[0], message_events[1]
    assistant_start, assistant_end = message_events[2], message_events[-1]
    assert user_start["message"]["id"] == user_end["message"]["id"]
    assert assistant_start["message"]["id"] == assistant_end["message"]["id"]

    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["state"] == "idle"
    assert snapshot["live_message_id"] is None
    assert [message["content"][0]["text"] for message in snapshot["messages"]] == [
        "Hi",
        "Hello",
    ]
    assert snapshot["tool_executions"]["tool-1"] == {
        "toolCallId": "tool-1",
        "toolName": "read",
        "args": {"path": "README.md"},
        "result": {"content": [{"type": "text", "text": "done"}]},
        "isError": False,
    }


def test_event_pump_continues_and_settles_while_browser_is_disconnected(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    continue_runtime = threading.Event()

    class BackgroundRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            await asyncio.to_thread(continue_runtime.wait)
            yield {
                "type": "message_start",
                "message": {"role": "assistant", "content": []},
            }
            yield {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Finished offline"}],
                },
            }
            yield {"type": "agent_settled"}
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = BackgroundRuntime()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a&after_revision=0"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json() == {"type": "agent_start"}

    continue_runtime.set()

    def settled_snapshot_exists() -> bool:
        snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
        return snapshot["state"] == "idle" and bool(snapshot["messages"])

    _wait_until(settled_snapshot_exists)
    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["messages"][0]["content"] == [{"type": "text", "text": "Finished offline"}]
    assert launcher.runtime.stopped is False


def test_reconnect_replays_events_produced_after_rest_snapshot(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    continue_runtime = threading.Event()

    class JournalRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            await asyncio.to_thread(continue_runtime.wait)
            yield {
                "type": "message_start",
                "message": {"role": "assistant", "content": []},
            }
            yield {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "contentIndex": 0,
                    "delta": "arrived after GET",
                },
            }
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = JournalRuntime()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a&after_revision=0"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json() == {"type": "agent_start"}

    snapshot_revision = client.client.get(f"/api/chatbox/sessions/{session_id}").json()[
        "snapshot_revision"
    ]
    continue_runtime.set()
    _wait_until(
        lambda: (
            client.client.app.state.chatbox_runtime_brokers[session_id].history.revision
            >= snapshot_revision + 2
        )
    )

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
        f"&after_revision={snapshot_revision}"
    ) as ws:
        _expect_runtime_ready(ws)
        started = ws.receive_json()
        updated = ws.receive_json()

    assert started["type"] == "message_start"
    assert isinstance(started["message"]["id"], str)
    assert updated == {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": "text_delta",
            "contentIndex": 0,
            "delta": "arrived after GET",
        },
    }


def test_pause_wakes_subscriber_and_releases_active_lease(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()

    async def settled_events() -> AsyncIterator[dict[str, object]]:
        yield {"type": "agent_start"}
        yield {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": "visible",
            },
        }
        yield {"type": "agent_settled"}
        await asyncio.Event().wait()

    launcher.runtime.events = settled_events  # type: ignore[method-assign]
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a&after_revision=0"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"
        assert ws.receive_json()["type"] == "message_update"
        assert ws.receive_json()["type"] == "agent_settled"
        response = client.client.post(f"/api/chatbox/sessions/{session_id}/pause")
        assert response.status_code == 200
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()

    assert exc_info.value.code == 1012
    assert launcher.runtime.stopped is True
    assert client.client.app.state.chatbox_active_websocket_sessions == set()
    assert client.client.app.state.chatbox_runtime_handles == {}
    assert client.client.app.state.chatbox_runtime_brokers == {}


def test_disconnected_session_expires_after_reconnect_grace(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chatbox_broker_module, "_DISCONNECTED_GRACE_SECONDS", 0.1)
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a&after_revision=0"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"

    def session_is_suspended() -> bool:
        snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
        return (
            launcher.runtime.stopped
            and snapshot["state"] == "idle"
            and snapshot["session_state"] == "paused"
        )

    _wait_until(session_is_suspended, timeout=5.0)
    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["state"] == "idle"
    assert snapshot["session_state"] == "paused"
    current = client.client.get("/api/chatbox/sessions/current").json()
    assert current["session_id"] == session_id
    assert current["session_state"] == "paused"
    assert client.client.app.state.chatbox_proxy_grants == {}
    assert client.client.app.state.chatbox_runtime_handles == {}
    assert client.client.app.state.chatbox_runtime_brokers == {}


def test_suspend_retains_current_pointer_and_activate_advances_generation(
    client: ChatboxTestClient,
) -> None:
    _create_default_provider(client.store)
    created = client.client.post("/api/chatbox/sessions").json()
    session_id = created["session_id"]

    suspended_response = client.client.post(f"/api/chatbox/sessions/{session_id}/suspend")

    assert suspended_response.status_code == 200
    suspended = suspended_response.json()
    assert suspended["session_state"] == "paused"
    current = client.client.get("/api/chatbox/sessions/current").json()
    assert current["session_id"] == session_id
    assert current["session_state"] == "paused"

    activated_response = client.client.post(f"/api/chatbox/sessions/{session_id}/activate")

    assert activated_response.status_code == 200
    activated = activated_response.json()
    assert activated["session_state"] == "active"
    assert activated["runtime_generation"] == created["runtime_generation"] + 1


def test_queue_overflow_checkpoints_snapshot_before_requesting_resync(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class OverflowRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            yield {
                "type": "message_start",
                "message": {"role": "assistant", "content": []},
            }
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    monkeypatch.setattr(chatbox_broker_module, "_SUBSCRIBER_QUEUE_SIZE", 1)
    runtime = OverflowRuntime()
    workspace_root = tmp_path / "overflow-workspace"
    workspace_root.mkdir()

    async def exercise() -> tuple[object, int]:
        async def terminal() -> None:
            return None

        async def checkpoint() -> None:
            return None

        broker = ChatboxRuntimeBroker(
            chatbox_session_id=session_id,
            runtime=runtime,  # type: ignore[arg-type]
            workspace_root=workspace_root,
            on_terminal=terminal,
            on_checkpoint=checkpoint,
        )
        queue = await broker.subscribe(0)
        broker.start()
        deadline = asyncio.get_running_loop().time() + 1.0
        while broker.history.revision < 2:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("broker did not project both overflow events")
            await asyncio.sleep(0.01)
        item = await asyncio.wait_for(queue.get(), timeout=1.0)
        while not isinstance(item, ChatboxBrokerResyncError):
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        revision = broker.history.revision
        await broker.stop()
        return item, revision

    item, revision = asyncio.run(exercise())

    assert isinstance(item, ChatboxBrokerResyncError)
    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["snapshot_revision"] == revision
    assert snapshot["live_message_id"] is not None


def test_broker_persists_history_outside_the_event_loop(
    client: ChatboxTestClient,
    tmp_path: Path,
) -> None:
    class OneEventRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    workspace_root = tmp_path / "threaded-history-workspace"
    workspace_root.mkdir()
    apply_threads: list[int] = []

    async def exercise() -> int:
        async def terminal() -> None:
            return None

        async def checkpoint() -> None:
            return None

        broker = ChatboxRuntimeBroker(
            chatbox_session_id=session_id,
            runtime=OneEventRuntime(),  # type: ignore[arg-type]
            workspace_root=workspace_root,
            on_terminal=terminal,
            on_checkpoint=checkpoint,
        )
        original_apply = broker.history.apply

        def track_apply(event: dict[str, object]) -> tuple[int, dict[str, object]]:
            apply_threads.append(threading.get_ident())
            return original_apply(event)

        broker.history.apply = track_apply  # type: ignore[method-assign]
        queue = await broker.subscribe(0)
        event_loop_thread = threading.get_ident()
        broker.start()
        assert await asyncio.wait_for(queue.get(), timeout=1.0) == {"type": "agent_start"}
        await broker.stop()
        return event_loop_thread

    event_loop_thread = asyncio.run(exercise())

    assert apply_threads
    assert all(thread_id != event_loop_thread for thread_id in apply_threads)


def test_broker_stop_drains_inflight_history_operation(
    client: ChatboxTestClient,
    tmp_path: Path,
) -> None:
    class OneEventRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    workspace_root = tmp_path / "drained-history-workspace"
    workspace_root.mkdir()
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    async def exercise() -> None:
        async def terminal() -> None:
            return None

        async def checkpoint() -> None:
            return None

        broker = ChatboxRuntimeBroker(
            chatbox_session_id=session_id,
            runtime=OneEventRuntime(),  # type: ignore[arg-type]
            workspace_root=workspace_root,
            on_terminal=terminal,
            on_checkpoint=checkpoint,
        )
        original_apply = broker.history.apply

        def blocking_apply(event: dict[str, object]) -> tuple[int, dict[str, object]]:
            worker_started.set()
            try:
                if not release_worker.wait(timeout=1.0):
                    raise TimeoutError("history worker was not released")
                return original_apply(event)
            finally:
                worker_finished.set()

        broker.history.apply = blocking_apply  # type: ignore[method-assign]
        broker.start()
        deadline = asyncio.get_running_loop().time() + 1.0
        while not worker_started.is_set():
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("history worker did not start")
            await asyncio.sleep(0.01)

        stop_task = asyncio.create_task(broker.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()
        release_worker.set()
        await asyncio.wait_for(stop_task, timeout=1.0)
        assert worker_finished.is_set()

    asyncio.run(exercise())


def test_history_checkpoint_fails_when_session_disappears(
    client: ChatboxTestClient,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    history = ChatboxHistory(session_id)

    with db_session.SessionLocal() as database:
        session = database.get(ChatboxSession, session_id)
        assert session is not None
        database.delete(session)
        database.commit()

    with pytest.raises(LookupError, match="disappeared before persist"):
        history.checkpoint()

    assert history.persisted_revision == 0


def test_get_hides_other_workspace_session(client: ChatboxTestClient) -> None:
    _create_default_provider(client.store)
    with db_session.SessionLocal() as database:
        database.add(
            ChatboxSession(
                id="foreign-session",
                workspace_id="workspace-b",
                user_id="user-b",
                provider_id="provider-b",
                lifecycle_state="idle",
            )
        )
        database.commit()
    response = client.client.get("/api/chatbox/sessions/foreign-session")
    assert response.status_code == 404


def test_restart_stops_runtime_revokes_grant_and_returns_fresh_session(
    client: ChatboxTestClient,
) -> None:
    provider_id = _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    runtime = launcher.runtime
    client.client.app.state.pi_runtime_launcher = launcher
    client.client.app.state.chatbox_runtime_handles = {session_id: runtime}
    proxy_token = issue_internal_proxy_grant(
        client.client.app,
        chatbox_session_id=session_id,
        workspace_id="workspace-a",
        provider_id=provider_id,
    )

    response = client.client.post(f"/api/chatbox/sessions/{session_id}/restart")

    assert response.status_code == 201
    restarted = response.json()
    assert restarted["session_id"] != session_id
    assert restarted["provider_id"] == provider_id
    assert restarted["state"] == "idle"
    assert restarted["messages"] == []
    assert runtime.stopped is True
    assert session_id not in client.client.app.state.chatbox_runtime_handles
    assert proxy_token not in client.client.app.state.chatbox_proxy_grants


def test_delete_requires_archive_and_permanently_removes_session(
    client: ChatboxTestClient,
) -> None:
    provider_id = _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    client.client.app.state.pi_runtime_launcher = launcher
    client.client.app.state.chatbox_runtime_handles = {session_id: launcher.runtime}
    proxy_token = issue_internal_proxy_grant(
        client.client.app,
        chatbox_session_id=session_id,
        workspace_id="workspace-a",
        provider_id=provider_id,
    )

    active_delete = client.client.delete(f"/api/chatbox/sessions/{session_id}")
    assert active_delete.status_code == 409

    archived = client.client.post(f"/api/chatbox/sessions/{session_id}/archive")
    assert archived.status_code == 200
    response = client.client.delete(f"/api/chatbox/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert launcher.runtime.stopped is True
    assert proxy_token not in client.client.app.state.chatbox_proxy_grants
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").status_code == 404


def test_archived_view_and_unarchive_are_workspace_user_scoped(
    client: ChatboxTestClient,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]

    archived = client.client.post(f"/api/chatbox/sessions/{session_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["session_state"] == "archived"
    assert client.client.get("/api/chatbox/sessions?view=conversations").json()["items"] == []
    archived_items = client.client.get("/api/chatbox/sessions?view=archived").json()["items"]
    assert [item["session_id"] for item in archived_items] == [session_id]

    restored = client.client.post(f"/api/chatbox/sessions/{session_id}/unarchive")
    assert restored.status_code == 200
    assert restored.json()["session_state"] == "paused"
    assert restored.json()["is_current"] is False
    assert client.client.get("/api/chatbox/sessions?view=archived").json()["items"] == []


def test_websocket_rejects_bad_token(
    client: ChatboxTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.chatbox.workspace_rbac_enforced", lambda: True)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.client.websocket_connect(
            "/api/chatbox/sessions/missing?workspace_id=workspace-a"
        ):
            pass
    assert exc_info.value.code == 1008


def test_websocket_rejects_workspace_resolution_error(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_workspace_resolution(_websocket: object) -> None:
        raise AppError(ErrorCode.WORKSPACE_NOT_FOUND, "Workspace not found")

    monkeypatch.setattr("app.api.chatbox._ws_context", fail_workspace_resolution)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.client.websocket_connect(
            "/api/chatbox/sessions/missing?workspace_id=workspace-a"
        ):
            pass

    assert exc_info.value.code == 1008


def test_websocket_projects_events_and_forwards_commands(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    monkeypatch.setattr(
        "app.api.chatbox.get_pi_runtime_launcher",
        lambda _app: launcher,
    )
    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json() == {"type": "agent_start"}
        assert ws.receive_json() == {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": "visible",
            },
        }
        command = {"id": "command-1", "type": "prompt", "message": "hello"}
        ws.send_json(command)
    assert launcher.runtime.commands == [command]
    _wait_until(lambda: session_id not in client.client.app.state.chatbox_active_websocket_sessions)
    proxy_token = launcher.start_kwargs["proxy_token"]
    grant = client.client.app.state.chatbox_proxy_grants[proxy_token]
    assert grant.chatbox_session_id == session_id
    assert grant.workspace_id == "workspace-a"
    assert grant.provider_id == launcher.start_kwargs["provider_id"]
    assert launcher.start_kwargs["model_context_window"] == 128_000
    assert launcher.start_kwargs["model_max_tokens"] == 4_096
    assert launcher.start_kwargs["model_reasoning"] is False
    assert launcher.runtime.stopped is False
    assert client.client.app.state.chatbox_runtime_handles == {session_id: launcher.runtime}
    assert client.client.app.state.chatbox_active_websocket_sessions == set()
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "active"


def test_websocket_bootstraps_projected_history_when_checkpoint_is_missing(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    projected_messages = [
        {
            "id": "browser-user-id",
            "role": "user",
            "content": [{"type": "text", "text": "Remember alpha."}],
            "timestamp": 1,
        },
        {
            "id": "browser-assistant-id",
            "role": "assistant",
            "api": "anthropic-messages",
            "provider": "doc-conv-proxy",
            "model": "model-a",
            "content": [{"type": "text", "text": "I will remember alpha."}],
            "usage": {
                "input": 1,
                "output": 1,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 2,
                "cost": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0,
                },
            },
            "stopReason": "stop",
            "timestamp": 2,
        },
    ]
    with db_session.SessionLocal() as database:
        persisted = database.get(ChatboxSession, session_id)
        assert persisted is not None
        persisted.messages_json = projected_messages
        persisted.checkpoint_ref = None
        persisted.checkpoint_hash = None
        database.commit()

    launcher = FakeLauncher()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"

    assert launcher.start_kwargs["checkpoint_path"] is None
    assert launcher.start_kwargs["legacy_messages"] == projected_messages


def test_websocket_starts_fresh_runtime_for_admission_only_history(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    suffix = "admission-only"
    with db_session.SessionLocal() as database:
        persisted = database.get(ChatboxSession, session_id)
        assert persisted is not None
        persisted.messages_json = [
            {
                "id": f"admission-user-{suffix}",
                "role": "user",
                "content": [{"type": "text", "text": "Write a poem."}],
            },
            {
                "id": f"admission-platform-{suffix}",
                "role": "platform",
                "content": [
                    {
                        "type": "admission",
                        "status": "reject_out_of_scope",
                        "reasonCode": "not_pressroom_scope",
                    }
                ],
            },
        ]
        persisted.checkpoint_ref = None
        persisted.checkpoint_hash = None
        database.commit()

    launcher = FakeLauncher()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"

    assert launcher.start_kwargs["checkpoint_path"] is None
    assert launcher.start_kwargs["legacy_messages"] is None


def test_websocket_rejects_out_of_scope_turn_before_runtime_dispatch(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_out_of_scope(**_kwargs: object) -> str:
        return "reject_out_of_scope"

    client.client.app.state.agent_admission_classifier = reject_out_of_scope
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    monkeypatch.setattr("app.api.chatbox.get_pi_runtime_launcher", lambda _app: launcher)

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"
        assert ws.receive_json()["type"] == "message_update"
        ws.send_json(
            {
                "id": "out-of-scope",
                "type": "prompt",
                "message": "Write a poem about sunsets.",
            }
        )
        rejected_user = ws.receive_json()
        rejected_platform = ws.receive_json()
        assert rejected_user["type"] == "message_end"
        assert rejected_user["message"]["role"] == "user"
        assert rejected_platform["type"] == "message_end"
        assert rejected_platform["message"]["role"] == "platform"
        assert rejected_platform["message"]["content"] == [
            {
                "type": "admission",
                "status": "reject_out_of_scope",
                "reasonCode": "not_pressroom_scope",
            }
        ]

    assert launcher.runtime.commands == []
    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["title"] == "Write a poem about sunsets."
    assert snapshot["preview"] == "Write a poem about sunsets."
    assert snapshot["first_settled_at"] is None


def test_websocket_runtime_failure_closes_once_and_logs_safely(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingRuntime(FakeRuntime):
        async def send_command(self, command: dict[str, object]) -> None:
            raise PiRuntimeError("sensitive upstream detail")

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = FailingRuntime()
    monkeypatch.setattr(
        "app.api.chatbox.get_pi_runtime_launcher",
        lambda _app: launcher,
    )

    with caplog.at_level("WARNING", logger="app.api.chatbox"):
        with client.client.websocket_connect(
            f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
        ) as ws:
            _expect_runtime_ready(ws)
            assert ws.receive_json()["type"] == "agent_start"
            assert ws.receive_json()["type"] == "message_update"
            ws.send_json({"id": "command-1", "type": "prompt", "message": "hello"})
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert exc_info.value.code == 1011
    assert any("error_type=PiRuntimeError" in record.getMessage() for record in caplog.records)
    assert all("sensitive upstream detail" not in record.getMessage() for record in caplog.records)
    _wait_until(lambda: launcher.runtime.stopped)
    assert client.client.app.state.chatbox_proxy_grants == {}
    assert client.client.app.state.chatbox_runtime_handles == {}
    assert client.client.app.state.chatbox_active_websocket_sessions == set()
    _wait_until(
        lambda: client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "dead",
        timeout=5.0,
    )


def test_websocket_transport_failure_preserves_live_runtime(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class TransportFailingRuntime(FakeRuntime):
        async def send_command(self, command: dict[str, object]) -> None:
            raise RuntimeError("sensitive transport detail")

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = TransportFailingRuntime()
    monkeypatch.setattr(
        "app.api.chatbox.get_pi_runtime_launcher",
        lambda _app: launcher,
    )

    with caplog.at_level("WARNING", logger="app.api.chatbox"):
        with client.client.websocket_connect(
            f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
        ) as ws:
            _expect_runtime_ready(ws)
            assert ws.receive_json()["type"] == "agent_start"
            assert ws.receive_json()["type"] == "message_update"
            ws.send_json({"id": "command-1", "type": "prompt", "message": "hello"})
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert exc_info.value.code == 1011
    _wait_until(lambda: session_id not in client.client.app.state.chatbox_active_websocket_sessions)
    assert launcher.runtime.stopped is False
    assert client.client.app.state.chatbox_runtime_handles == {session_id: launcher.runtime}
    assert len(client.client.app.state.chatbox_proxy_grants) == 1
    assert any("error_type=RuntimeError" in record.getMessage() for record in caplog.records)
    assert all("sensitive transport detail" not in record.getMessage() for record in caplog.records)
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "active"


def test_agent_settled_updates_durable_lifecycle_without_stopping_runtime(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SettlingRuntime(FakeRuntime):
        async def events(self) -> AsyncIterator[dict[str, object]]:
            yield {"type": "agent_start"}
            yield {"type": "agent_settled"}
            await asyncio.Event().wait()

    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    launcher.runtime = SettlingRuntime()
    monkeypatch.setattr(
        "app.api.chatbox.get_pi_runtime_launcher",
        lambda _app: launcher,
    )

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
    ) as ws:
        _expect_runtime_ready(ws)
        assert ws.receive_json()["type"] == "agent_start"
        assert ws.receive_json()["type"] == "agent_settled"

    _wait_until(lambda: session_id not in client.client.app.state.chatbox_active_websocket_sessions)
    assert launcher.runtime.stopped is False
    assert client.client.app.state.chatbox_runtime_handles == {session_id: launcher.runtime}
    assert len(client.client.app.state.chatbox_proxy_grants) == 1
    snapshot = client.client.get(f"/api/chatbox/sessions/{session_id}").json()
    assert snapshot["state"] == "idle"
    assert snapshot["first_settled_at"] is not None
    assert snapshot["title"] == "New conversation"
    with db_session.SessionLocal() as database:
        persisted = database.get(ChatboxSession, session_id)
        assert persisted is not None
        assert persisted.checkpoint_revision >= 2
        assert persisted.checkpoint_hash is not None


def test_websocket_accept_failure_does_not_start_runtime_or_issue_grant(
    client: ChatboxTestClient,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    client.client.app.state.pi_runtime_launcher = launcher

    class RejectingWebSocket:
        app = client.client.app
        query_params = {"workspace_id": "workspace-a"}

        async def accept(self) -> None:
            raise RuntimeError("handshake failed")

    asyncio.run(chatbox_websocket(RejectingWebSocket(), session_id))  # type: ignore[arg-type]

    assert launcher.start_count == 0
    assert getattr(client.client.app.state, "chatbox_proxy_grants", {}) == {}
    assert getattr(client.client.app.state, "chatbox_runtime_handles", {}) == {}
    assert getattr(client.client.app.state, "chatbox_active_websocket_sessions", set()) == set()
    assert getattr(client.client.app.state, "chatbox_runtime_locks", {}) == {}
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "idle"


def test_fresh_session_rejects_future_revision_before_starting_runtime(
    client: ChatboxTestClient,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    launcher = FakeLauncher()
    client.client.app.state.pi_runtime_launcher = launcher

    with client.client.websocket_connect(
        f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a&after_revision=1"
    ) as ws:
        _expect_runtime_restoring(ws)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()

    assert exc_info.value.code == 1012
    assert launcher.start_count == 0
    assert getattr(client.client.app.state, "chatbox_proxy_grants", {}) == {}
    assert getattr(client.client.app.state, "chatbox_runtime_handles", {}) == {}
    assert getattr(client.client.app.state, "chatbox_runtime_brokers", {}) == {}
    assert getattr(client.client.app.state, "chatbox_active_websocket_sessions", set()) == set()
    assert getattr(client.client.app.state, "chatbox_runtime_locks", {}) == {}
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "idle"


def test_websocket_initial_subprocess_failure_closes_safely_and_revokes_grant(
    client: ChatboxTestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]

    async def fail_start(_handle: PiRuntimeHandle) -> None:
        raise OSError("sensitive executable path")

    monkeypatch.setattr(PiRuntimeHandle, "start", fail_start)
    client.client.app.state.pi_runtime_launcher = PiRuntimeLauncher(node_bin=sys.executable)

    with caplog.at_level("WARNING", logger="app.api.chatbox"):
        with client.client.websocket_connect(
            f"/api/chatbox/sessions/{session_id}?workspace_id=workspace-a"
        ) as ws:
            _expect_runtime_restoring(ws)
            with pytest.raises(WebSocketDisconnect) as exc_info:
                failed = ws.receive_json()
                assert failed["type"] == "runtime_status"
                assert failed["status"] == "failed"
                ws.receive_json()

    assert exc_info.value.code == 1011
    assert client.client.app.state.chatbox_proxy_grants == {}
    assert client.client.app.state.chatbox_runtime_handles == {}
    assert client.client.app.state.chatbox_active_websocket_sessions == set()
    assert all("sensitive executable path" not in record.getMessage() for record in caplog.records)
    assert client.client.get(f"/api/chatbox/sessions/{session_id}").json()["state"] == "dead"


def test_concurrent_connections_start_one_runtime(
    client: ChatboxTestClient,
) -> None:
    provider_id = _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    chat_session = _get_session(session_id, "workspace-a")
    provider = client.store.get_provider(provider_id)
    assert provider is not None
    launcher = FakeLauncher()
    client.client.app.state.pi_runtime_launcher = launcher
    websocket = SimpleNamespace(app=client.client.app)

    async def start_twice() -> tuple[FakeRuntime, FakeRuntime]:
        first, second = await asyncio.gather(
            _runtime_for_session(websocket, chat_session, provider),  # type: ignore[arg-type]
            _runtime_for_session(websocket, chat_session, provider),  # type: ignore[arg-type]
        )
        return first, second  # type: ignore[return-value]

    first, second = asyncio.run(start_twice())

    assert first is second is launcher.runtime
    assert launcher.start_count == 1
    assert client.client.app.state.chatbox_runtime_handles == {session_id: launcher.runtime}
    assert client.client.app.state.chatbox_runtime_locks == {}


def test_runtime_lock_propagates_cancellation_and_cleans_entry(
    client: ChatboxTestClient,
) -> None:
    async def cancel_inside_lock() -> None:
        async with _runtime_lock(client.client.app, "cancelled-session"):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancel_inside_lock())

    assert client.client.app.state.chatbox_runtime_locks == {}


def test_released_connection_reclaims_same_runtime_without_dual_consumers(
    client: ChatboxTestClient,
) -> None:
    provider_id = _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    chat_session = _get_session(session_id, "workspace-a")
    provider = client.store.get_provider(provider_id)
    assert provider is not None
    launcher = FakeLauncher()
    client.client.app.state.pi_runtime_launcher = launcher
    websocket = SimpleNamespace(app=client.client.app)

    async def claim_twice() -> None:
        first = await _claim_runtime_for_session(  # type: ignore[arg-type]
            websocket, chat_session, provider
        )
        assert first is launcher.runtime

        class RetryableConflictWebSocket:
            app = client.client.app
            query_params = {"workspace_id": "workspace-a"}

            def __init__(self) -> None:
                self.accepted = False
                self.close_code: int | None = None
                self.messages: list[dict[str, object]] = []

            async def accept(self) -> None:
                self.accepted = True

            async def send_json(self, message: dict[str, object]) -> None:
                self.messages.append(message)

            async def close(self, code: int) -> None:
                self.close_code = code

        conflicting_websocket = RetryableConflictWebSocket()
        await chatbox_websocket(conflicting_websocket, session_id)  # type: ignore[arg-type]
        assert conflicting_websocket.accepted is True
        assert conflicting_websocket.messages == [
            {
                "type": "runtime_status",
                "status": "restoring",
                "runtime_generation": chat_session.runtime_generation,
            }
        ]
        assert conflicting_websocket.close_code == 1013

        await _release_websocket_session(client.client.app, session_id)
        reclaimed = await _claim_runtime_for_session(  # type: ignore[arg-type]
            websocket, chat_session, provider
        )
        assert reclaimed is first
        await _stop_session_runtime(
            client.client.app,
            session_id,
            lifecycle_state="idle",
            release_websocket=True,
        )

    asyncio.run(claim_twice())

    assert launcher.start_count == 1
    assert client.client.app.state.chatbox_active_websocket_sessions == set()
    assert client.client.app.state.chatbox_runtime_locks == {}
    assert client.client.app.state.chatbox_proxy_grants == {}


def test_stop_waits_for_inflight_start_and_removes_runtime(
    client: ChatboxTestClient,
) -> None:
    provider_id = _create_default_provider(client.store)
    session_id = client.client.post("/api/chatbox/sessions").json()["session_id"]
    chat_session = _get_session(session_id, "workspace-a")
    provider = client.store.get_provider(provider_id)
    assert provider is not None
    websocket = SimpleNamespace(app=client.client.app)

    async def exercise_race() -> FakeRuntime:
        class BlockingLauncher(FakeLauncher):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def start_session(self, *_args: object, **kwargs: object) -> FakeRuntime:
                self.start_count += 1
                self.start_kwargs = kwargs
                self.started.set()
                await self.release.wait()
                return self.runtime

        launcher = BlockingLauncher()
        client.client.app.state.pi_runtime_launcher = launcher
        start_task = asyncio.create_task(
            _runtime_for_session(websocket, chat_session, provider)  # type: ignore[arg-type]
        )
        await launcher.started.wait()
        stop_task = asyncio.create_task(_stop_session_runtime(client.client.app, session_id))
        await asyncio.sleep(0)
        assert stop_task.done() is False
        launcher.release.set()
        await start_task
        await stop_task
        return launcher.runtime

    runtime = asyncio.run(exercise_race())

    assert runtime.stopped is True
    assert session_id not in client.client.app.state.chatbox_runtime_handles
    assert client.client.app.state.chatbox_runtime_locks == {}
    assert client.client.app.state.chatbox_proxy_grants == {}
