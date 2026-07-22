from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.workspace_permissions import WorkspaceRole
from tests._api_workspace_contract import (
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


@pytest.fixture
def authenticated_owner_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    install_authenticated_workspace(
        app,
        monkeypatch,
        role=WorkspaceRole.OWNER,
    )
    yield
    remove_authenticated_workspace(app)
    get_settings.cache_clear()


def _make_client_with_orchestrator_stub(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _create_from_workflow(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            task_id="task_node_run_001",
            status=SimpleNamespace(value="pending"),
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(create_from_workflow=_create_from_workflow),
    )
    monkeypatch.setattr(app.state, "dag_scheduler", object(), raising=False)
    monkeypatch.setattr(app.state, "engine_client", object(), raising=False)
    monkeypatch.setattr(app.state, "event_store", object(), raising=False)
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(upsert_snapshot=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.api.tasks._start_dag_run",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.api.tasks.uuid4",
        lambda: SimpleNamespace(hex="node_run_001"),
    )

    return TestClient(app)


def test_node_run_accepts_engine_node_and_returns_task(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_owner_workspace: None,
) -> None:
    client = _make_client_with_orchestrator_stub(monkeypatch)
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": "utf-8"}},
        ],
        "connections": [{"source": "input_1", "target": "engine_1"}],
    }

    response = client.post(
        "/api/tasks/node-run",
        data={"workflow": str(workflow).replace("'", '"'), "node_id": "engine_1"},
        files={"files": ("input.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "task_node_run_001"
    assert body["status"] == "pending"
    assert body["node_id"] == "engine_1"


def test_node_run_rejects_non_engine_node(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_owner_workspace: None,
) -> None:
    client = _make_client_with_orchestrator_stub(monkeypatch)
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [{"source": "input_1", "target": "end_1"}],
    }

    response = client.post(
        "/api/tasks/node-run",
        data={"workflow": str(workflow).replace("'", '"'), "node_id": "end_1"},
        files={"files": ("input.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
