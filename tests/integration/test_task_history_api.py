from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests._api_workspace_contract import TEST_WORKSPACE_ID
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest_asyncio.fixture
async def isolated_task_history_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> AsyncIterator[Path]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'tasks.sqlite3'}")
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
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    get_workflow_store.cache_clear()
    async with app.router.lifespan_context(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


def _workflow_definition() -> dict[str, object]:
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


async def _wait_for_terminal_status(client: AsyncClient, task_id: str) -> dict[str, object]:
    await app.state.task_orchestrator.wait_for_completion(
        task_id,
        timeout=5.0,
        workspace_id=TEST_WORKSPACE_ID,
    )
    response = await client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_task_history_supports_filters_and_pagination(
    isolated_task_history_state: Path,
) -> None:
    workflow = _workflow_definition()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save_response = await client.post(
            "/api/workflows/save",
            json={"name": "history-wf", "definition": workflow},
        )
        workflow_id = save_response.json()["data"]["id"]

        upload_response = await client.post(
            "/api/files/upload",
            files={"file": ("history.txt", b"history", "text/plain")},
        )
        file_id = upload_response.json()["file_id"]

        execute_response = await client.post(
            f"/api/workflows/{workflow_id}/execute",
            json={"file_ids": [file_id]},
        )
        assert execute_response.status_code == 202
        task_id = execute_response.json()["task_id"]
        await _wait_for_terminal_status(client, task_id)

        history_response = await client.get(
            "/api/tasks/history",
            params={"page": 1, "limit": 20, "status": "completed", "workflow_id": workflow_id},
        )

    assert history_response.status_code == 200
    body = history_response.json()
    assert body["success"] is True
    assert body["meta"]["page"] == 1
    assert body["meta"]["limit"] == 20
    assert body["meta"]["total"] >= 1
    assert any(item["task_id"] == task_id for item in body["data"])
    target = next(item for item in body["data"] if item["task_id"] == task_id)
    assert target["workflow_id"] == workflow_id
    assert target["workflow_name"] == "history-wf"
    assert target["node_summary"]["total"] == 3
    assert target["duration_ms"] is not None


@pytest.mark.anyio
async def test_task_history_invalid_status_returns_400(isolated_task_history_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks/history", params={"status": "weird"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_STATUS_FILTER"
