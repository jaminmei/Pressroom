from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.files import get_file_store
from app.config import WorkspaceRuntimeEnvError, get_settings, require_workspace_runtime_env
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.api_key import ApiKey
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.task_run import TaskRun
from app.models.db.workflow_record import WorkflowRecord
from app.services.api_usage_service import ApiUsageService
from tests.integration.workspace_api_support import (
    create_workspace,
    reset_db_runtime,
    skip_discover_seed_configs,
)


@pytest.fixture(params=["true"])
def dual_write_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> Iterator[tuple[TestClient, str, list[dict[str, object]]]]:
    database_path = tmp_path / "workspace-dual-write.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", str(request.param))
    provider_db_path = tmp_path / "providers.sqlite3"
    provider_key = Fernet.generate_key().decode()
    monkeypatch.setenv("PROVIDER_DB_PATH", str(provider_db_path))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", provider_key)
    for name, value in {
        "BACKEND_WORKSPACE_RBAC_ENFORCED": str(request.param),
        "BACKEND_DATABASE_URL": f"sqlite+pysqlite:///{database_path}",
        "BACKEND_PROVIDER_DB_PATH": str(provider_db_path),
        "BACKEND_PROVIDER_ENCRYPTION_KEY": provider_key,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    queued: list[dict[str, object]] = []

    def capture_task(**kwargs: object) -> None:
        queued.append(kwargs)

    def capture_evaluation(coro: object) -> SimpleNamespace:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.tasks._start_dag_run", capture_task)
    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", capture_evaluation)

    with TestClient(app) as client:
        app.state.dag_scheduler = SimpleNamespace()
        app.state.engine_client = SimpleNamespace()
        app.state.event_store = SimpleNamespace()
        app.state.running_tasks = {}
        registration = client.post(
            "/api/auth/register",
            json={
                "email": f"dual-{request.param}@example.com",
                "password": "StrongerPassword123!",
                "name": "Dual Write",
            },
        )
        assert registration.status_code == 201
        workspace_id = create_workspace(client, name=f"Dual Write {request.param}")
        assert client.post(f"/api/workspaces/{workspace_id}/switch").status_code == 200
        yield client, workspace_id, queued

    reset_db_runtime()


def test_public_runtime_rejects_disabled_workspace_rbac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(
            WorkspaceRuntimeEnvError,
            match="public deployments require workspace RBAC enforcement",
        ):
            require_workspace_runtime_env("backend")
    finally:
        get_settings.cache_clear()


def _workflow_definition() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": "utf-8"}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }


def _assert_readiness() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check-workspace-rbac-readiness.py", "--mode", "full"],
        check=False,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_rows_and_queue_metadata_always_resolve_workspace(
    dual_write_client: tuple[TestClient, str, list[dict[str, object]]],
) -> None:
    client, workspace_id, queued = dual_write_client

    workflow_response = client.post(
        "/api/workflows", json={"name": "Dual workflow", "definition": _workflow_definition()}
    )
    assert workflow_response.status_code == 201
    workflow_id = workflow_response.json()["workflow_id"]

    dataset_response = client.post(
        "/api/test-sets", json={"name": "Dual dataset", "description": None}
    )
    assert dataset_response.status_code == 201
    test_set_id = dataset_response.json()["id"]
    assert dataset_response.json()["workspace_id"] == workspace_id

    document_response = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("sample.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )
    assert document_response.status_code == 201
    assert len(document_response.json()["uploaded"]) == 1

    staged_response = client.post(
        "/api/files/upload",
        files={"file": ("staged.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert staged_response.status_code == 200
    staged_file_id = staged_response.json()["file_id"]
    staged_file = get_file_store().get(staged_file_id)
    assert staged_file is not None
    assert staged_file.workspace_id == workspace_id
    assert staged_file.uploaded_by_user_id

    task_response = client.post(
        "/api/tasks",
        data={"workflow": json.dumps(_workflow_definition()), "file_ids": "[]"},
    )
    assert task_response.status_code == 202
    task_id = task_response.json()["task_id"]
    assert queued[-1]["workspace_id"] == workspace_id

    evaluation_response = client.post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow_id, "name": "Dual evaluation"},
    )
    assert evaluation_response.status_code == 201
    evaluation_run_id = evaluation_response.json()["id"]

    key_response = client.post(
        "/api/admin/api-keys", json={"workflow_id": workflow_id, "description": "Dual key"}
    )
    assert key_response.status_code == 201
    key_id = key_response.json()["id"]

    asyncio.run(
        ApiUsageService().record_invocation(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            workflow_run_id=task_id,
            api_key_id=key_id,
            api_key_prefix=key_response.json()["key_prefix"],
            endpoint_kind="json_run",
            http_status=202,
            workflow_status="pending",
            response_time_ms=1,
            input_metadata=None,
            error=None,
            storage_bytes=0,
            created_at=datetime.now(timezone.utc),
            finished_at=None,
        )
    )

    with db_session.SessionLocal() as session:
        assert session.get(WorkflowRecord, workflow_id).workspace_id == workspace_id
        assert (
            session.execute(
                text("SELECT workspace_id FROM test_sets WHERE id = :id"), {"id": test_set_id}
            ).scalar_one()
            == workspace_id
        )
        assert session.get(EvaluationRun, evaluation_run_id).workspace_id == workspace_id
        assert session.get(TaskRun, task_id).workspace_id == workspace_id
        api_key = session.get(ApiKey, key_id)
        assert api_key is not None
        assert api_key.workspace_id == workspace_id
        assert (
            session.execute(
                text("SELECT workspace_id FROM api_invocations WHERE workflow_id = :workflow_id"),
                {"workflow_id": workflow_id},
            ).scalar_one()
            == workspace_id
        )

    _assert_readiness()
