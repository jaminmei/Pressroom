from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.tasks import RunningTaskContext
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthUser
from app.models.db.task_run import TaskRun
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


@dataclass(frozen=True, slots=True)
class FailedEvent:
    event_type: str
    node_id: str


class DoneTask:
    def done(self) -> bool:
        return True


class FakeDagResult:
    completed: dict[str, object] = {}


class FakeScheduler:
    async def run(self, *_args: object, **_kwargs: object) -> FakeDagResult:
        return FakeDagResult()


class FakeEventStore:
    def __init__(self) -> None:
        self.deleted_nodes: set[str] = set()

    def get_events(self, _run_id: str) -> list[FailedEvent]:
        return [FailedEvent(event_type="failed", node_id="engine_1")]

    def delete_events_for_nodes(self, _run_id: str, node_ids: set[str]) -> None:
        self.deleted_nodes = node_ids

    def compute_state(self, _run_id: str) -> dict[str, object]:
        return {}


@pytest.fixture()
def task_rbac_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    enable_rbac(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'tasks-rbac.sqlite3'}")
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())
    yield


def _task_app(*, workspace_id: str, user_id: str, email: str, role: WorkspaceRole) -> FastAPI:
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api")
    app.state.running_tasks = {}
    app.state.event_store = FakeEventStore()
    app.state.dag_scheduler = FakeScheduler()
    app.state.engine_client = object()
    app.state.auth_resolver = None
    app.state.provider_store = None
    make_workspace_client(
        app,
        user=AuthUser(id=user_id, email=email),
        workspace_id=workspace_id,
        role=role,
    )
    return app


def _workspace_user(email: str, role: WorkspaceRole) -> tuple[str, str]:
    user_id = make_user(db_session.SessionLocal, email)
    workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=user_id,
        member_role=role,
    )
    return user_id, workspace_id


def _insert_task(
    task_id: str,
    workspace_id: str,
    *,
    status: str = "completed",
    workflow: dict[str, object] | None = None,
    input_files: list[dict[str, object]] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with db_session.SessionLocal() as session:
        session.add(
            TaskRun(
                id=task_id,
                status=status,
                workspace_id=workspace_id,
                created_at=now,
                completed_at=now,
                results_json='[{"result_id":"r1","content":"ok"}]',
                workflow_json=json.dumps(workflow) if workflow is not None else None,
                input_files_json=json.dumps(input_files) if input_files is not None else None,
                updated_at=now,
            )
        )
        session.commit()


def test_runner_can_retry_workspace_task(
    task_rbac_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, workspace_id = _workspace_user("runner@example.com", WorkspaceRole.RUNNER)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner@example.com",
        role=WorkspaceRole.RUNNER,
    )
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[WorkflowConnection(source="engine_1", target="end_1")],
    )
    app.state.running_tasks["task_retry"] = RunningTaskContext(
        task_id="task_retry",
        run_id="task_retry",
        workflow=workflow,
        asyncio_task=cast(asyncio.Task[object], DoneTask()),
        workspace_id=workspace_id,
    )
    monkeypatch.setattr("app.api.tasks._start_dag_run", lambda **_kwargs: None)

    response = TestClient(app).post("/api/tasks/task_retry/retry")

    assert response.status_code == 202
    assert response.json()["failed_nodes"] == ["engine_1"]


def test_viewer_can_view_workspace_task_results(task_rbac_db: None) -> None:
    user_id, workspace_id = _workspace_user("viewer@example.com", WorkspaceRole.VIEWER)
    _insert_task("task_result", workspace_id)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="viewer@example.com",
        role=WorkspaceRole.VIEWER,
    )

    response = TestClient(app).get("/api/tasks/task_result/results")

    assert response.status_code == 200
    assert response.json()["results"][0]["content"] == "ok"


def test_cross_workspace_task_returns_404(task_rbac_db: None) -> None:
    owner_id = make_user(db_session.SessionLocal, "owner@example.com")
    first_workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=owner_id,
    )
    second_workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=owner_id,
    )
    _insert_task("task_private", first_workspace_id)
    app = _task_app(
        workspace_id=second_workspace_id,
        user_id=owner_id,
        email="owner@example.com",
        role=WorkspaceRole.OWNER,
    )

    response = TestClient(app).get("/api/tasks/task_private")

    assert response.status_code == 404


def test_history_filters_by_workspace(task_rbac_db: None) -> None:
    owner_id = make_user(db_session.SessionLocal, "history-owner@example.com")
    first_workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=owner_id,
    )
    second_workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=owner_id,
    )
    _insert_task("task_first", first_workspace_id)
    _insert_task("task_second", second_workspace_id)
    app = _task_app(
        workspace_id=first_workspace_id,
        user_id=owner_id,
        email="history-owner@example.com",
        role=WorkspaceRole.OWNER,
    )

    response = TestClient(app).get("/api/tasks/history")

    assert response.status_code == 200
    assert {item["task_id"] for item in response.json()["data"]} == {"task_first"}


def test_runner_can_cancel_running_task(task_rbac_db: None) -> None:
    user_id, workspace_id = _workspace_user("runner-cancel@example.com", WorkspaceRole.RUNNER)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner-cancel@example.com",
        role=WorkspaceRole.RUNNER,
    )
    workflow = WorkflowDefinition(
        nodes=[WorkflowNode(id="engine_1", type="engine/ocr", config={})],
        connections=[],
    )
    app.state.running_tasks["task_cancel"] = RunningTaskContext(
        task_id="task_cancel",
        run_id="task_cancel",
        workflow=workflow,
        asyncio_task=cast(asyncio.Task[object], DoneTask()),
        workspace_id=workspace_id,
    )

    response = TestClient(app).delete("/api/tasks/task_cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert app.state.running_tasks["task_cancel"].cancel_requested is True


@pytest.mark.parametrize("status", ["pending", "running"])
def test_runner_can_durably_cancel_snapshot_only_task(
    task_rbac_db: None,
    status: str,
) -> None:
    user_id, workspace_id = _workspace_user(
        f"runner-cancel-{status}@example.com",
        WorkspaceRole.RUNNER,
    )
    task_id = f"task_snapshot_{status}"
    _insert_task(task_id, workspace_id, status=status)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email=f"runner-cancel-{status}@example.com",
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(app).delete(f"/api/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["idempotent"] is False
    with db_session.SessionLocal() as session:
        persisted = session.get(TaskRun, task_id)
        assert persisted is not None
        assert persisted.status == "cancelled"
        assert persisted.completed_at is not None


def test_snapshot_cancel_is_idempotent(task_rbac_db: None) -> None:
    user_id, workspace_id = _workspace_user(
        "runner-cancel-idempotent@example.com",
        WorkspaceRole.RUNNER,
    )
    _insert_task("task_cancelled", workspace_id, status="cancelled")
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner-cancel-idempotent@example.com",
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(app).delete("/api/tasks/task_cancelled")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task_cancelled",
        "status": "cancelled",
        "idempotent": True,
    }


def test_runner_can_retry_snapshot_as_new_task(task_rbac_db: None) -> None:
    user_id, workspace_id = _workspace_user(
        "runner-snapshot-retry@example.com",
        WorkspaceRole.RUNNER,
    )
    workflow = {
        "nodes": [{"id": "input", "type": "input/text", "config": {}}],
        "connections": [],
    }
    _insert_task(
        "task_failed",
        workspace_id,
        status="failed",
        workflow=workflow,
        input_files=[{"node_id": "input", "file_id": "file_123"}],
    )
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner-snapshot-retry@example.com",
        role=WorkspaceRole.RUNNER,
    )
    created_at = datetime.now(timezone.utc)
    create_from_workflow = AsyncMock(
        return_value=SimpleNamespace(
            task_id="task_retried",
            status=SimpleNamespace(value="pending"),
            created_at=created_at,
        )
    )
    app.state.task_orchestrator = SimpleNamespace(
        create_from_workflow=create_from_workflow,
    )

    response = TestClient(app).post("/api/tasks/task_failed/retry")

    assert response.status_code == 202
    assert response.json()["task_id"] == "task_retried"
    assert response.json()["retried_from_task_id"] == "task_failed"
    create_from_workflow.assert_awaited_once()
    call = create_from_workflow.await_args
    assert call.kwargs["file_ids"] == ["file_123"]
    assert call.kwargs["workspace_id"] == workspace_id
    assert call.kwargs["requested_by_user_id"] == user_id


@pytest.mark.parametrize(
    ("workflow", "input_files"),
    [
        (None, None),
        (
            {
                "nodes": [{"id": "input", "type": "input/text", "config": {}}],
                "connections": [],
            },
            [],
        ),
    ],
)
def test_snapshot_retry_requires_workflow_and_file_bindings(
    task_rbac_db: None,
    workflow: dict[str, object] | None,
    input_files: list[dict[str, object]] | None,
) -> None:
    user_id, workspace_id = _workspace_user(
        "runner-retry-unavailable@example.com",
        WorkspaceRole.RUNNER,
    )
    _insert_task(
        "task_retry_unavailable",
        workspace_id,
        status="failed",
        workflow=workflow,
        input_files=input_files,
    )
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner-retry-unavailable@example.com",
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(app).post("/api/tasks/task_retry_unavailable/retry")

    assert response.status_code == 409
    assert response.json()["error_code"] == "RETRY_NOT_AVAILABLE"


def test_viewer_cannot_cancel_task(task_rbac_db: None) -> None:
    user_id, workspace_id = _workspace_user("viewer-cancel@example.com", WorkspaceRole.VIEWER)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="viewer-cancel@example.com",
        role=WorkspaceRole.VIEWER,
    )

    response = TestClient(app).delete("/api/tasks/task_cancel")

    assert response.status_code == 403
    assert response.json()["detail"] == "run.cancel required"


@pytest.mark.parametrize("path", ["/api/tasks", "/api/tasks/node-run"])
def test_runner_cannot_execute_raw_workflow(task_rbac_db: None, path: str) -> None:
    user_id, workspace_id = _workspace_user("runner-raw@example.com", WorkspaceRole.RUNNER)
    app = _task_app(
        workspace_id=workspace_id,
        user_id=user_id,
        email="runner-raw@example.com",
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(app).post(path)

    assert response.status_code == 403
    assert response.json()["detail"] == "workflow.edit_draft required"
