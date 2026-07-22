from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import RunningTaskContext, get_task_orchestrator, get_task_run_repository
from app.api.tasks import get_file_store as get_task_file_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.models.workflow import WorkflowDefinition
from tests._api_workspace_contract import (
    TEST_USER_ID,
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


def _reset_database_runtime() -> None:
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture
def isolated_regression_task_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'tasks.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.sqlite3"))
    get_settings.cache_clear()
    _reset_database_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(
            UserAccount(
                id=TEST_USER_ID,
                email="regression-task@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
            )
        )
        session.add(
            Workspace(
                id=TEST_WORKSPACE_ID,
                name="Regression Task Workspace",
                slug=None,
                description=None,
                owner_user_id=TEST_USER_ID,
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_regression_task",
                workspace_id=TEST_WORKSPACE_ID,
                user_id=TEST_USER_ID,
                role="owner",
            )
        )
        session.commit()

    install_authenticated_workspace(app, monkeypatch)
    app.state.dag_scheduler = object()
    app.state.engine_client = object()
    app.state.provider_store = None
    app.state.event_store = type(
        "RegressionEventStore",
        (),
        {
            "get_events": staticmethod(lambda _run_id: []),
            "compute_state": staticmethod(lambda _run_id: {}),
            "delete_events": staticmethod(lambda _run_id: 0),
        },
    )()
    app.state.running_tasks = {}

    def _start_without_external_engine(**kwargs: object) -> None:
        task_id = str(kwargs["task_id"])
        running_tasks = kwargs["running_tasks"]
        workflow = kwargs["workflow"]
        current_task = asyncio.current_task()
        assert isinstance(running_tasks, dict)
        assert isinstance(workflow, WorkflowDefinition)
        assert current_task is not None
        running_tasks[task_id] = RunningTaskContext(
            task_id=task_id,
            run_id=str(kwargs["run_id"]),
            workflow=workflow,
            asyncio_task=current_task,
            workspace_id=str(kwargs["workspace_id"]),
        )

    monkeypatch.setattr("app.api.tasks._start_dag_run", _start_without_external_engine)
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    get_task_orchestrator.cache_clear()
    get_task_run_repository.cache_clear()
    yield tmp_path
    app.state.running_tasks = {}
    remove_authenticated_workspace(app)
    get_task_run_repository.cache_clear()
    get_task_orchestrator.cache_clear()
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    _reset_database_runtime()


@pytest.mark.anyio
async def test_post_tasks_still_returns_task_id(isolated_regression_task_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"].startswith("task_")
    assert body["status"] == "pending"


@pytest.mark.anyio
async def test_get_task_response_keeps_existing_keys(isolated_regression_task_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post(
            "/api/tasks",
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        )
        task_id = create.json()["task_id"]
        status = await client.get(f"/api/tasks/{task_id}")

    assert status.status_code == 200
    payload = status.json()
    for key in ["task_id", "status", "created_at", "updated_at", "progress", "node_states"]:
        assert key in payload


@pytest.mark.anyio
async def test_delete_task_still_supported(isolated_regression_task_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post(
            "/api/tasks",
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        )
        task_id = create.json()["task_id"]
        response = await client.delete(f"/api/tasks/{task_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] in {"cancelled", "completed", "failed", "partial_completed"}
