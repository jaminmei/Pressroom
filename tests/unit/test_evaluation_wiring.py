from __future__ import annotations

import asyncio
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.auth import get_auth_service
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.workflow_store import WorkflowStore

TEST_PASSWORD = "Public-Test-Password-2026!"


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


async def _skip_provider_discovery(_provider_store: object) -> int:
    return 0


def _configure_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_name: str,
) -> None:
    database_path = tmp_path / database_name
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / f"{database_name}.providers"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AUTH_SESSION_SECRET", "evaluation-test-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("AUTH_SESSION_SECURE", "false")
    monkeypatch.setenv("ORCHESTRATOR_MODE", "serial")
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", _skip_provider_discovery)
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())


def _register_personal_workspace(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": TEST_PASSWORD, "name": "Unit Tester"},
    )
    assert response.status_code == 201
    user_id = response.json()["data"]["user"]["id"]
    return f"ws_personal_{user_id}"


def _sample_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/document", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


def test_api_router_registers_evaluation_routes() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/test-sets" in paths
    assert "/api/test-sets/{test_set_id}/documents/upload" in paths
    assert "/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth" in paths
    assert "/api/evaluation-runs/{run_id}" in paths


def test_main_lifespan_initializes_evaluation_service(monkeypatch, tmp_path: Path) -> None:
    _configure_lifespan(monkeypatch, tmp_path, "evaluation-service.sqlite3")

    with TestClient(app):
        assert hasattr(app.state, "evaluation_repository")


def test_main_lifespan_initializes_evaluation_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_lifespan(monkeypatch, tmp_path, "evaluation-wiring.sqlite3")

    with TestClient(app) as client:
        _register_personal_workspace(client, "dependencies@example.com")
        response = client.get("/api/test-sets")

        assert hasattr(client.app.state, "test_set_repository")
        assert hasattr(client.app.state, "test_set_storage")
        assert hasattr(client.app.state, "ground_truth_repository")
        assert hasattr(client.app.state, "evaluation_repository")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_main_lifespan_cancels_and_drains_evaluation_background_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_lifespan(monkeypatch, tmp_path, "evaluation-shutdown.sqlite3")

    cancelled = Event()

    async def _run_batch(**kwargs: object) -> None:
        _ = kwargs
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with TestClient(app) as client:
        workspace_id = _register_personal_workspace(client, "shutdown@example.com")
        client.app.state.evaluation_service = SimpleNamespace(run_batch=_run_batch)
        workflow_store = WorkflowStore()
        workflow = workflow_store.create(
            name="Shutdown Workflow",
            definition=_sample_definition(),
            workspace_id=workspace_id,
        )
        client.app.state.workflow_store = workflow_store
        repository = client.app.state.test_set_repository
        test_set = asyncio.run(
            repository.create_test_set(
                name="Shutdown Set",
                description=None,
                workspace_id=workspace_id,
            )
        )
        asyncio.run(
            repository.create_test_document(
                test_set_id=test_set.id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_shutdown_invoice.pdf",
                size_bytes=100,
                page_count=1,
            )
        )
        created = client.post(
            f"/api/test-sets/{test_set.id}/evaluation-runs",
            json={"workflow_id": workflow.id, "name": "Shutdown Run"},
        )
        assert created.status_code == 201
        assert len(client.app.state.evaluation_background_tasks) == 1
        time.sleep(0.05)

    background_tasks = client.app.state.evaluation_background_tasks
    assert len(background_tasks) == 0
    assert cancelled.is_set()
