from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.fixture
def isolated_workflow_import_export_state(
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
    get_workflow_store.cache_clear()
    with TestClient(app):
        yield tmp_path
    get_workflow_store.cache_clear()
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
async def test_export_and_import_round_trip(isolated_workflow_import_export_state: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save_response = await client.post(
            "/api/workflows/save",
            json={"name": "round-trip", "description": "demo", "definition": _definition()},
        )
        workflow_id = save_response.json()["data"]["id"]

        export_response = await client.get(f"/api/workflows/{workflow_id}/export")
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("application/json")
        assert "attachment; filename=" in export_response.headers.get("content-disposition", "")

        exported = export_response.json()
        assert exported["format_version"] == "1.0"
        assert exported["workflow"]["name"] == "round-trip"

        import_response = await client.post("/api/workflows/import", json=exported)
        assert import_response.status_code == 200
        imported_id = import_response.json()["data"]["id"]

        re_export = await client.get(f"/api/workflows/{imported_id}/export")
        assert re_export.status_code == 200
        re_exported = re_export.json()
        assert re_exported["workflow"]["definition"] == exported["workflow"]["definition"]


@pytest.mark.anyio
async def test_import_rejects_unsupported_format_version(
    isolated_workflow_import_export_state: Path,
) -> None:
    payload = {
        "format_version": "99.0",
        "workflow": {
            "name": "bad",
            "description": None,
            "definition": _definition(),
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workflows/import", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_FORMAT_VERSION"
    assert body["details"] is None
