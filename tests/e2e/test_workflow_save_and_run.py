from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.api.tasks import get_task_run_repository, reset_task_orchestrator
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.models.task import TaskStatus
from app.models.workflow import WorkflowDefinition
from app.services.workflow_execution import PersistedWorkflowExecution
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
def isolated_e2e_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'e2e.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.sqlite3"))
    get_settings.cache_clear()
    _reset_database_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(
            UserAccount(
                id=TEST_USER_ID,
                email="e2e-workflow@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
            )
        )
        session.add(
            Workspace(
                id=TEST_WORKSPACE_ID,
                name="E2E Workflow Workspace",
                slug=None,
                description=None,
                owner_user_id=TEST_USER_ID,
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_e2e_workflow",
                workspace_id=TEST_WORKSPACE_ID,
                user_id=TEST_USER_ID,
                role="owner",
            )
        )
        session.commit()

    install_authenticated_workspace(app, monkeypatch)
    app.state.provider_store = None
    app.state.running_tasks = {}
    app.state.event_store = SimpleNamespace(get_events=lambda _run_id: [])

    async def _execute_locally(
        definition: WorkflowDefinition,
        execution: PersistedWorkflowExecution,
    ) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        task_id = "task_e2e_local"
        await get_task_run_repository().upsert_snapshot(
            task_id=task_id,
            status="completed",
            workflow_id=execution.workflow_id,
            workflow_name=execution.workflow_name,
            run_name=execution.run_name,
            workspace_id=execution.workspace_id,
            created_at=now,
            completed_at=now,
            duration_ms=1,
            node_summary={"total": 3, "completed": 3, "failed": 0},
            result_preview="hello e2e",
            results=[
                {
                    "result_id": "result_e2e",
                    "node_id": "end_1",
                    "node_type": "end/final",
                    "output_format": "markdown",
                    "content": "hello e2e",
                    "metadata": {"processing_time_ms": 1},
                }
            ],
            error=None,
            workflow=definition.model_dump(mode="json"),
            updated_at=now,
        )
        return SimpleNamespace(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            created_at=now,
        )

    app.state.workflow_execution = SimpleNamespace(execute=_execute_locally)
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    reset_task_orchestrator()
    get_workflow_store.cache_clear()
    get_task_run_repository.cache_clear()
    yield tmp_path
    remove_authenticated_workspace(app)
    app.state.running_tasks = {}
    get_task_run_repository.cache_clear()
    get_workflow_store.cache_clear()
    reset_task_orchestrator()
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    _reset_database_runtime()


def _workflow() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }


async def _wait_for_done(client: AsyncClient, task_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "partial_completed", "failed", "cancelled"}:
            return payload
        await asyncio.sleep(0.02)
    raise AssertionError(f"Task {task_id} timeout")


@pytest.mark.anyio
async def test_save_execute_history_and_export_flow(isolated_e2e_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save = await client.post(
            "/api/workflows/save",
            json={"name": "e2e-flow", "description": "pipeline", "definition": _workflow()},
        )
        assert save.status_code == 200
        workflow_id = save.json()["data"]["id"]

        upload = await client.post(
            "/api/files/upload",
            files={"file": ("e2e.txt", b"hello e2e", "text/plain")},
        )
        assert upload.status_code == 200
        file_id = upload.json()["file_id"]

        execute = await client.post(
            f"/api/workflows/{workflow_id}/execute",
            json={"file_ids": [file_id]},
        )
        assert execute.status_code == 202
        task_id = execute.json()["task_id"]

        final_task = await _wait_for_done(client, task_id)
        assert final_task["status"] in {"completed", "partial_completed"}

        history = await client.get("/api/tasks/history", params={"workflow_id": workflow_id})
        assert history.status_code == 200
        assert any(item["task_id"] == task_id for item in history.json()["data"])

        exported = await client.get(f"/api/workflows/{workflow_id}/export")
        assert exported.status_code == 200
        assert exported.json()["workflow"]["name"] == "e2e-flow"
