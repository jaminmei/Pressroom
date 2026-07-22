"""Workflow CRUD, validation, and error-handling integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.fixture
def isolated_wf_crud(
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
    get_file_store.cache_clear()
    get_workflow_store.cache_clear()
    with TestClient(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


def _valid_workflow() -> dict:
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


# ---------------------------------------------------------------------------
# 1. Workflow create → get → verify structure
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_create_get_verify_structure(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/workflows",
            json={"name": "crud-test", "definition": _valid_workflow()},
        )
        assert resp.status_code == 201
        body = resp.json()
        wf_id = body["workflow_id"]
        assert wf_id.startswith("wf_")
        assert body["validation"]["valid"] is True
        assert body["execution_plan"]["total_nodes"] == 3

        get_resp = await c.get(f"/api/workflows/{wf_id}")
        assert get_resp.status_code == 200
        wf = get_resp.json()
        assert wf["id"] == wf_id
        assert wf["name"] == "crud-test"
        assert len(wf["definition"]["nodes"]) == 3
        assert len(wf["definition"]["connections"]) == 2
        assert "created_at" in wf
        assert "updated_at" in wf


# ---------------------------------------------------------------------------
# 2. Workflow with cycle → rejected (400 + WORKFLOW_CYCLE)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_cycle_rejected(isolated_wf_crud: Path) -> None:
    wf = _valid_workflow()
    wf["connections"].append({"source": "end_1", "target": "input_1"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/workflows", json={"definition": wf})

    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    codes = [e["code"] for e in body["details"]["errors"]]
    assert "WORKFLOW_CYCLE" in codes


# ---------------------------------------------------------------------------
# 3. Workflow with disconnected nodes → accepted with warning
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_disconnected_nodes_returns_warning(isolated_wf_crud: Path) -> None:
    wf = _valid_workflow()
    wf["nodes"].append({"id": "orphan_1", "type": "engine/text", "config": {}})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/workflows", json={"definition": wf})

    assert resp.status_code == 201
    body = resp.json()
    assert body["validation"]["valid"] is True
    codes = [e["code"] for e in body["validation"]["warnings"]]
    assert "WORKFLOW_ORPHAN_NODE" in codes


# ---------------------------------------------------------------------------
# 4. Workflow with empty nodes list → rejected
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_empty_nodes_rejected(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/workflows",
            json={"definition": {"nodes": [], "connections": []}},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert len(body["details"]["errors"]) > 0


# ---------------------------------------------------------------------------
# 5. Workflow with duplicate node IDs → rejected
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_duplicate_node_ids_rejected(isolated_wf_crud: Path) -> None:
    wf = {
        "nodes": [
            {"id": "dup", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "dup", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "dup", "target": "end_1"},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/workflows", json={"definition": wf})

    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    codes = [e["code"] for e in body["details"]["errors"]]
    assert "DUPLICATE_NODE_ID" in codes


# ---------------------------------------------------------------------------
# 6. Get non-existent workflow → 404
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_get_nonexistent_workflow_404(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/workflows/wf_does_not_exist")

    assert resp.status_code == 404
    assert resp.json()["error_code"] == "WORKFLOW_NOT_FOUND"


# ---------------------------------------------------------------------------
# 7. Create workflow → execute with missing file_id → 400
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_execute_missing_file_id_400(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create_resp = await c.post(
            "/api/workflows",
            json={"name": "exec-test", "definition": _valid_workflow()},
        )
        assert create_resp.status_code == 201
        wf_id = create_resp.json()["workflow_id"]

        resp = await c.post(
            f"/api/workflows/{wf_id}/execute",
            json={"file_ids": ["file_nonexistent"]},
        )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "WORKFLOW_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 8. Create workflow → execute with non-existent workflow_id → 404
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_execute_nonexistent_workflow_404(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/workflows/wf_ghost/execute",
            json={"file_ids": []},
        )

    assert resp.status_code == 404
    assert resp.json()["error_code"] == "WORKFLOW_NOT_FOUND"


# ---------------------------------------------------------------------------
# 9. Workflow validation returns execution_plan with correct total_nodes
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_execution_plan_total_nodes(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/workflows",
            json={"definition": _valid_workflow()},
        )

    assert resp.status_code == 201
    plan = resp.json()["execution_plan"]
    assert plan["total_nodes"] == 3
    assert isinstance(plan["execution_order"], list)
    assert len(plan["execution_order"]) == 3


# ---------------------------------------------------------------------------
# 10. Multiple workflows can coexist independently
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_multiple_workflows_coexist(isolated_wf_crud: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ids = []
        for i in range(3):
            resp = await c.post(
                "/api/workflows",
                json={"name": f"wf-{i}", "definition": _valid_workflow()},
            )
            assert resp.status_code == 201
            ids.append(resp.json()["workflow_id"])

        assert len(set(ids)) == 3

        for idx, wf_id in enumerate(ids):
            get_resp = await c.get(f"/api/workflows/{wf_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["name"] == f"wf-{idx}"
