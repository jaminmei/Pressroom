from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app


def _sample_definition(encoding: str = "utf-8") -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": encoding}},
            {"id": "output_1", "type": "output/markdown", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture()
def workflow_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_path = tmp_path / "workflow-conflict.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    client = TestClient(app)
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "StrongerPassword123!",
            "name": "Alice",
        },
    )
    assert register_response.status_code == 201
    return client


def test_workflow_save_requires_authenticated_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workflow-auth.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    with TestClient(app) as client:
        response = client.post(
            "/api/workflows/save",
            json={"name": "Invoice OCR", "definition": _sample_definition()},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"


def test_stale_base_version_returns_workflow_version_conflict(workflow_client: TestClient) -> None:
    create_response = workflow_client.post(
        "/api/workflows/save",
        json={"name": "Invoice OCR", "definition": _sample_definition()},
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]

    update_response = workflow_client.post(
        "/api/workflows/save",
        json={
            "workflow_id": created["id"],
            "workflow_key": created["workflow_key"],
            "base_version": created["latest_version"],
            "name": "Invoice OCR v2",
            "definition": _sample_definition("big5"),
        },
    )
    assert update_response.status_code == 200

    stale_response = workflow_client.post(
        "/api/workflows/save",
        json={
            "workflow_id": created["id"],
            "workflow_key": created["workflow_key"],
            "base_version": created["latest_version"],
            "name": "Invoice OCR stale",
            "definition": _sample_definition("utf-16"),
        },
    )

    assert stale_response.status_code == 409
    payload = stale_response.json()
    assert payload["error_code"] == "WORKFLOW_VERSION_CONFLICT"
    assert payload["details"]["workflow_key"] == created["workflow_key"]
    assert payload["details"]["latest_version"] == created["latest_version"] + 1


def test_save_as_new_name_creates_new_workflow_lineage(workflow_client: TestClient) -> None:
    original_response = workflow_client.post(
        "/api/workflows/save",
        json={"name": "Invoice OCR", "definition": _sample_definition()},
    )
    assert original_response.status_code == 200
    original = original_response.json()["data"]

    save_as_response = workflow_client.post(
        "/api/workflows/save",
        json={
            "name": "Invoice OCR Save As",
            "description": "forked after conflict review",
            "definition": _sample_definition("big5"),
        },
    )

    assert save_as_response.status_code == 200
    forked = save_as_response.json()["data"]
    assert forked["id"] != original["id"]
    assert forked["workflow_key"] != original["workflow_key"]
    assert forked["name"] == "Invoice OCR Save As"
    assert forked["latest_version"] == 1


def test_workflow_versions_can_be_loaded_by_workflow_key(workflow_client: TestClient) -> None:
    create_response = workflow_client.post(
        "/api/workflows/save",
        json={"name": "Invoice OCR", "definition": _sample_definition()},
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]

    update_response = workflow_client.post(
        "/api/workflows/save",
        json={
            "workflow_id": created["id"],
            "workflow_key": created["workflow_key"],
            "base_version": created["latest_version"],
            "name": "Invoice OCR v2",
            "definition": _sample_definition("big5"),
        },
    )
    assert update_response.status_code == 200

    versions_response = workflow_client.get(f"/api/workflows/{created['workflow_key']}/versions")

    assert versions_response.status_code == 200
    payload = versions_response.json()
    assert payload["success"] is True
    assert payload["meta"]["total"] == 2
    assert [item["version"] for item in payload["data"]] == [2, 1]
