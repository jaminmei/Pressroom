from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.api.tasks import get_task_orchestrator
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
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
def isolated_regression_workflow_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflows.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.sqlite3"))
    get_settings.cache_clear()
    _reset_database_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(
            UserAccount(
                id=TEST_USER_ID,
                email="regression-workflow@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
            )
        )
        session.add(
            Workspace(
                id=TEST_WORKSPACE_ID,
                name="Regression Workflow Workspace",
                slug=None,
                description=None,
                owner_user_id=TEST_USER_ID,
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_regression_workflow",
                workspace_id=TEST_WORKSPACE_ID,
                user_id=TEST_USER_ID,
                role="owner",
            )
        )
        session.commit()

    install_authenticated_workspace(app, monkeypatch)
    app.state.provider_store = None
    app.state.workflow_execution = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                task_id="task_regression_workflow",
                status=SimpleNamespace(value="pending"),
                created_at=datetime.now(timezone.utc),
            )
        )
    )
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    get_task_orchestrator.cache_clear()
    get_workflow_store.cache_clear()
    yield tmp_path
    remove_authenticated_workspace(app)
    get_workflow_store.cache_clear()
    get_task_orchestrator.cache_clear()
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    _reset_database_runtime()


def _definition() -> dict[str, object]:
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


@pytest.mark.anyio
async def test_post_workflows_still_creates_workflow(
    isolated_regression_workflow_state: Path,
) -> None:
    payload = {"name": "legacy", "definition": _definition()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workflows", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workflow_id"].startswith("wf_")
    assert body["validation"]["valid"] is True


@pytest.mark.anyio
async def test_execute_workflow_still_returns_task_info(
    isolated_regression_workflow_state: Path,
) -> None:
    payload = {"name": "legacy", "definition": _definition()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/api/workflows", json=payload)
        assert create.status_code == 201, create.text
        workflow_id = create.json()["workflow_id"]

        upload = await client.post(
            "/api/files/upload",
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        )
        file_id = upload.json()["file_id"]

        execute = await client.post(
            f"/api/workflows/{workflow_id}/execute",
            json={"file_ids": [file_id]},
        )

    assert execute.status_code == 202
    body = execute.json()
    assert body["workflow_id"] == workflow_id
    assert body["task_id"].startswith("task_")


@pytest.mark.anyio
async def test_get_workflow_still_returns_definition(
    isolated_regression_workflow_state: Path,
) -> None:
    payload = {"name": "legacy", "definition": _definition()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/api/workflows", json=payload)
        assert create.status_code == 201, create.text
        workflow_id = create.json()["workflow_id"]
        response = await client.get(f"/api/workflows/{workflow_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == workflow_id
    assert "definition" in body
