from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.api.tasks import get_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests._api_workspace_contract import TEST_WORKSPACE_ID
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest_asyncio.fixture
async def isolated_workflow_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> AsyncIterator[Path]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.db"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.delenv("SKIP_DAG_INIT", raising=False)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    monkeypatch.setattr(
        "app.services.task_orchestrator.TaskOrchestrator._append_event_log_fire_and_forget",
        lambda *_args, **_kwargs: None,
    )
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    get_settings.cache_clear()
    get_file_store.cache_clear()
    get_workflow_store.cache_clear()
    async with app.router.lifespan_context(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


def _sample_workflow() -> dict[str, object]:
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


async def _wait_for_terminal_task(
    client: AsyncClient,
    task_id: str,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    await app.state.task_orchestrator.wait_for_completion(
        task_id,
        timeout=timeout_seconds,
        workspace_id=TEST_WORKSPACE_ID,
    )
    response = await client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_create_and_get_workflow(isolated_workflow_state: Path) -> None:
    payload = {
        "name": "text-workflow",
        "definition": _sample_workflow(),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post("/api/workflows", json=payload)

        assert create_response.status_code == 201
        create_body = create_response.json()
        assert create_body["validation"]["valid"] is True
        assert create_body["workflow_id"].startswith("wf_")
        assert create_body["execution_plan"]["total_nodes"] == 3
        workflow_id = create_body["workflow_id"]

        get_response = await client.get(f"/api/workflows/{workflow_id}")

    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["id"] == workflow_id
    assert get_body["name"] == "text-workflow"
    assert len(get_body["definition"]["nodes"]) == 3


@pytest.mark.anyio
async def test_create_workflow_rejects_cycle(isolated_workflow_state: Path) -> None:
    workflow = _sample_workflow()
    workflow["connections"].append({"source": "end_1", "target": "input_1"})
    payload = {"name": "bad-workflow", "definition": workflow}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workflows", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert any(error["code"] == "WORKFLOW_CYCLE" for error in body["details"]["errors"])


@pytest.mark.anyio
async def test_execute_workflow_with_uploaded_file_returns_task_id(
    isolated_workflow_state: Path,
) -> None:
    payload = {"name": "workflow-execute", "definition": _sample_workflow()}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post("/api/workflows", json=payload)
        assert create_response.status_code == 201
        workflow_id = create_response.json()["workflow_id"]

        upload_response = await client.post(
            "/api/files/upload",
            files={"file": ("doc.txt", b"hello workflow", "text/plain")},
        )
        assert upload_response.status_code == 200
        file_id = upload_response.json()["file_id"]

        execute_response = await client.post(
            f"/api/workflows/{workflow_id}/execute",
            json={"file_ids": [file_id]},
        )

        assert execute_response.status_code == 202
        execute_body = execute_response.json()
        assert execute_body["workflow_id"] == workflow_id
        assert execute_body["task_id"].startswith("task_")
        assert execute_body["status"] == "pending"

        task_payload = await _wait_for_terminal_task(client, execute_body["task_id"])
        assert task_payload["status"] in {"completed", "partial_completed"}


@pytest.mark.anyio
async def test_execute_workflow_returns_400_for_missing_file_id(
    isolated_workflow_state: Path,
) -> None:
    payload = {"name": "workflow-execute", "definition": _sample_workflow()}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post("/api/workflows", json=payload)
        assert create_response.status_code == 201
        workflow_id = create_response.json()["workflow_id"]

        response = await client.post(
            f"/api/workflows/{workflow_id}/execute",
            json={"file_ids": ["file_missing"]},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert "找不到檔案" in body["message"]


@pytest.mark.anyio
async def test_execute_workflow_returns_404_for_missing_workflow(
    isolated_workflow_state: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workflows/wf_missing/execute", json={"file_ids": []})

    assert response.status_code == 404
    assert response.json()["error_code"] == "WORKFLOW_NOT_FOUND"
