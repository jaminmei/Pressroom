from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.fixture
def isolated_orchestration_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'tasks.sqlite3'}")
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
    with TestClient(app):
        yield tmp_path
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


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


async def _wait_terminal(client: AsyncClient, task_id: str, timeout_seconds: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"completed", "partial_completed", "failed", "cancelled"}:
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(f"Task not completed in time: {last}")


async def _wait_persisted(client: AsyncClient, task_id: str, timeout_seconds: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if task_id not in app.state.running_tasks:
            response = await client.get(f"/api/tasks/{task_id}")
            assert response.status_code == 200
            return response.json()
        await asyncio.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not leave the running-task registry")


@pytest.mark.anyio
async def test_get_task_status_includes_persisted_node_progress(
    isolated_orchestration_storage: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/api/tasks",
            data={"workflow": json.dumps(_workflow())},
            files={"files": ("doc.txt", b"hello", "text/plain")},
        )
        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]

        await _wait_terminal(client, task_id)
        payload = await _wait_persisted(client, task_id)

    assert "node_states" in payload
    assert set(payload["node_states"]) == {"input_1", "engine_1", "end_1"}
    assert {node["status"] for node in payload["node_states"].values()} == {"completed"}
    assert payload["progress"]["completed_nodes"] == 3
    assert payload["progress"]["percentage"] == 100


@pytest.mark.anyio
async def test_delete_task_cancels_pending_or_running_task(
    isolated_orchestration_storage: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/api/tasks",
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )
        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]

        cancel_response = await client.delete(f"/api/tasks/{task_id}")

    assert cancel_response.status_code == 200
    body = cancel_response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "cancelled"
