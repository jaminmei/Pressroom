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
def shared_visibility_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[TestClient, TestClient]:
    database_path = tmp_path / "workflow-shared.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    client_a = TestClient(app)
    client_b = TestClient(app)

    register_a = client_a.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "StrongerPassword123!",
            "name": "Alice",
        },
    )
    assert register_a.status_code == 201

    register_b = client_b.post(
        "/api/auth/register",
        json={
            "email": "bob@example.com",
            "password": "StrongerPassword123!",
            "name": "Bob",
        },
    )
    assert register_b.status_code == 201

    return client_a, client_b


def test_workflow_versions_remain_private_to_the_owning_workspace(
    shared_visibility_clients: tuple[TestClient, TestClient],
) -> None:
    client_a, client_b = shared_visibility_clients

    save_response = client_a.post(
        "/api/workflows/save",
        json={"name": "Invoice OCR", "definition": _sample_definition()},
    )
    assert save_response.status_code == 200
    created = save_response.json()["data"]

    user_b_list = client_b.get("/api/workflows")
    assert user_b_list.status_code == 200
    assert user_b_list.json()["data"] == []

    user_a_update = client_a.post(
        "/api/workflows/save",
        json={
            "workflow_id": created["id"],
            "workflow_key": created["workflow_key"],
            "base_version": created["latest_version"],
            "name": "Invoice OCR v2",
            "definition": _sample_definition("big5"),
        },
    )
    assert user_a_update.status_code == 200

    user_b_detail = client_b.get(f"/api/workflows/{created['id']}")
    assert user_b_detail.status_code == 404
    assert user_b_detail.json()["error_code"] == "WORKFLOW_NOT_FOUND"
