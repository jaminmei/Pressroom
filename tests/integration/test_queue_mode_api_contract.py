from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.services.queue_task_runner import QueueTaskRunner
from tests.integration.workspace_api_support import reset_db_runtime


@pytest.fixture(autouse=True)
def _clear_task_run_repository_cache() -> Generator[None, None, None]:
    from app.api.tasks import get_task_run_repository

    get_task_run_repository.cache_clear()
    yield
    get_task_run_repository.cache_clear()


@pytest.fixture
def runtime_ready_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[None, None, None]:
    database_path = tmp_path / "queue-startup.sqlite3"
    provider_path = tmp_path / "queue-startup-providers.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(provider_path))
    monkeypatch.setenv("BACKEND_PROVIDER_DB_PATH", str(provider_path))
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    yield
    reset_db_runtime()


def _post_sample_task(client: TestClient):
    return client.post(
        "/api/tasks",
        files={"file": ("sample.txt", b"hello", "text/plain")},
        data={"engine": "ocr", "output_format": "markdown"},
    )


def test_create_task_accepts_queue_mode_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)

    client = TestClient(app)
    response = _post_sample_task(client)

    assert response.status_code in {202, 401}
    if response.status_code == 401:
        return
    payload = response.json()
    assert isinstance(payload.get("task_id"), str)
    assert payload.get("status") in {
        "pending",
        "running",
        "completed",
        "partial_completed",
        "failed",
        "cancelled",
    }


def test_normal_startup_uses_queue_runner_even_with_dag_components(
    monkeypatch: pytest.MonkeyPatch,
    runtime_ready_startup: None,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)

    class _EngineClient:
        async def close(self) -> None:
            return None

    def _init_dag_components(state: State) -> None:
        state.dag_scheduler = object()
        state.engine_client = _EngineClient()

    async def _skip_provider_discovery(_store: object) -> int:
        return 0

    monkeypatch.setattr("app.api.tasks.init_dag_components", _init_dag_components)
    monkeypatch.setattr("app.main.discover_seed_configs", _skip_provider_discovery)

    with TestClient(app):
        orchestrator = app.state.task_orchestrator
        assert isinstance(orchestrator._runner, QueueTaskRunner)


def test_create_task_accepts_queue_mode_via_alias(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    client = TestClient(app)
    response = _post_sample_task(client)

    assert response.status_code in {202, 401}
    if response.status_code == 401:
        return
    payload = response.json()
    assert isinstance(payload.get("task_id"), str)


@pytest.mark.parametrize(
    ("method", "path", "allowed_statuses"),
    [
        ("get", "/api/tasks/history", {200, 401}),
        ("get", "/api/tasks/task_dummy", {401, 404}),
        ("get", "/api/tasks/task_dummy/results", {401, 404, 409, 503}),
        ("get", "/api/tasks/task_dummy/results/res_001/download", {401, 404, 409, 503}),
        ("get", "/api/tasks/task_dummy/events", {401, 404}),
        ("delete", "/api/tasks/task_dummy", {401, 404}),
    ],
)
def test_task_endpoints_follow_runtime_contract_in_queue_mode(
    monkeypatch,
    method: str,
    path: str,
    allowed_statuses: set[int],
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)

    client = TestClient(app)
    response = getattr(client, method)(path)

    assert response.status_code in allowed_statuses

    payload = response.json()
    if response.status_code != 401 and isinstance(payload, dict) and "error_code" in payload:
        assert payload["error_code"] != "QUEUE_MODE_NOT_AVAILABLE"
        assert isinstance(payload.get("trace_id"), str)
