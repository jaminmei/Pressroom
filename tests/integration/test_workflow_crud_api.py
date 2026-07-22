from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.fixture
def isolated_workflow_crud_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.db"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.delenv("SKIP_DAG_INIT", raising=False)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    get_settings.cache_clear()
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    get_workflow_store.cache_clear()
    with TestClient(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


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
async def test_save_list_get_delete_workflow(isolated_workflow_crud_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save_response = await client.post(
            "/api/workflows/save",
            json={"name": "CRUD Workflow", "description": "for test", "definition": _definition()},
        )
        assert save_response.status_code == 200
        save_body = save_response.json()
        assert save_body["success"] is True
        workflow_id = save_body["data"]["id"]

        list_response = await client.get("/api/workflows", params={"page": 1, "limit": 10})
        assert list_response.status_code == 200
        list_body = list_response.json()
        assert list_body["success"] is True
        assert list_body["meta"]["total"] >= 1
        assert any(item["id"] == workflow_id for item in list_body["data"])

        get_response = await client.get(f"/api/workflows/{workflow_id}")
        assert get_response.status_code == 200
        get_body = get_response.json()
        assert get_body["id"] == workflow_id
        assert get_body["description"] == "for test"

        delete_response = await client.delete(f"/api/workflows/{workflow_id}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"success": True}

        get_deleted = await client.get(f"/api/workflows/{workflow_id}")
        assert get_deleted.status_code == 404


@pytest.mark.anyio
async def test_save_workflow_updates_existing(isolated_workflow_crud_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post(
            "/api/workflows/save",
            json={"name": "v1", "definition": _definition()},
        )
        create_data = create.json()["data"]
        workflow_id = create_data["id"]

        update = await client.post(
            "/api/workflows/save",
            json={
                "workflow_id": workflow_id,
                "base_version": create_data["latest_version"],
                "name": "v2",
                "description": "updated",
                "definition": _definition(),
            },
        )

    assert update.status_code == 200
    body = update.json()
    assert body["success"] is True
    assert body["data"]["id"] == workflow_id
    assert body["data"]["name"] == "v2"


@pytest.mark.anyio
async def test_workflow_validation_contract_includes_severity(
    isolated_workflow_crud_state: Path,
) -> None:
    bad_definition = {
        "nodes": [{"id": "input_1", "type": "input/text", "config": {}}],
        "connections": [],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/workflows/save",
            json={"name": "bad", "definition": bad_definition},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    issues = body["details"]["errors"]
    assert all("severity" in issue for issue in issues)
    assert any(issue["severity"] == "blocking" for issue in issues)
