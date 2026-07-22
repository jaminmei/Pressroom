from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_path = tmp_path / "auth-api.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    return TestClient(app)


def test_register_login_logout_and_me_flow(auth_client: TestClient) -> None:
    register_response = auth_client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "StrongerPassword123!",
            "name": "Alice",
        },
    )

    assert register_response.status_code == 201
    register_payload = register_response.json()
    assert register_payload["data"]["user"]["email"] == "alice@example.com"

    me_response = auth_client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["data"]["user"]["email"] == "alice@example.com"

    logout_response = auth_client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["success"] is True

    me_after_logout = auth_client.get("/api/auth/me")
    assert me_after_logout.status_code == 401
    assert me_after_logout.json()["error_code"] == "AUTH_REQUIRED"


def test_login_rejects_invalid_credentials(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "StrongerPassword123!",
            "name": "Alice",
        },
    )
    auth_client.post("/api/auth/logout")

    response = auth_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_INVALID_CREDENTIALS"
