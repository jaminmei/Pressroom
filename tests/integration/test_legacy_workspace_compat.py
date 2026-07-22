from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from tests.integration.workspace_api_support import (
    RegisteredClient,
    create_workspace,
    skip_discover_seed_configs,
)


@dataclass(frozen=True, slots=True)
class LegacyWorkspaceHarness:
    stack: ExitStack


@pytest.fixture()
def legacy_workspace_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[LegacyWorkspaceHarness]:
    database_path = tmp_path / "legacy-workspace-compat.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    provider_db_path = str(tmp_path / "providers.db")
    encryption_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("PROVIDER_DB_PATH", provider_db_path)
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("BACKEND_WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("BACKEND_DATABASE_URL", database_url)
    monkeypatch.setenv("BACKEND_PROVIDER_DB_PATH", provider_db_path)
    monkeypatch.setenv("BACKEND_PROVIDER_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())

    with ExitStack() as stack:
        yield LegacyWorkspaceHarness(stack=stack)


def _register(harness: LegacyWorkspaceHarness, email: str) -> RegisteredClient:
    client = harness.stack.enter_context(TestClient(app))
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongerPassword123!", "name": email},
    )
    assert response.status_code == 201
    return RegisteredClient(client=client, user_id=response.json()["data"]["user"]["id"])


def _set_last_workspace(user_id: str, workspace_id: str | None) -> None:
    with db_session.SessionLocal() as session:
        user = session.get(UserAccount, user_id)
        assert user is not None
        user.last_workspace_id = workspace_id
        session.add(user)
        session.commit()


def _set_membership_created_at(workspace_id: str, user_id: str, created_at: datetime) -> None:
    with db_session.SessionLocal() as session:
        membership = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        assert membership is not None
        membership.created_at = created_at
        session.add(membership)
        session.commit()


def _personal_workspace_id(user_id: str) -> str:
    return f"ws_personal_{user_id}"


def _assert_contains_baseline(actual: object, baseline: object) -> None:
    match baseline:
        case dict():
            assert isinstance(actual, dict)
            for key, value in baseline.items():
                assert key in actual
                _assert_contains_baseline(actual[key], value)
        case list():
            assert isinstance(actual, list)
            assert len(actual) >= len(baseline)
            for index, value in enumerate(baseline):
                _assert_contains_baseline(actual[index], value)
        case _:
            assert actual == baseline


def test_zero_workspace_request_auto_creates_personal_workspace(
    legacy_workspace_harness: LegacyWorkspaceHarness,
) -> None:
    user = _register(legacy_workspace_harness, "zero@example.com")

    response = user.client.get("/api/test-sets")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    with db_session.SessionLocal() as session:
        workspace = session.get(Workspace, f"ws_personal_{user.user_id}")
        assert workspace is not None
        assert workspace.owner_user_id == user.user_id
        membership = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.user_id,
            )
        )
        assert membership is not None
        assert membership.role == "owner"


def test_single_membership_without_workspace_context_uses_only_workspace(
    legacy_workspace_harness: LegacyWorkspaceHarness,
) -> None:
    user = _register(legacy_workspace_harness, "single@example.com")
    workspace_id = _personal_workspace_id(user.user_id)
    created = user.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Single Set", "description": None},
    )
    assert created.status_code == 201

    response = user.client.get("/api/test-sets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == created.json()["id"]
    assert payload["items"][0]["workspace_id"] == workspace_id


def test_multi_membership_without_workspace_context_prefers_last_workspace(
    legacy_workspace_harness: LegacyWorkspaceHarness,
) -> None:
    user = _register(legacy_workspace_harness, "last@example.com")
    first_workspace_id = _personal_workspace_id(user.user_id)
    second_workspace_id = create_workspace(user.client, name="Second Workspace")
    first_created = user.client.post(
        f"/api/test-sets?workspace_id={first_workspace_id}",
        json={"name": "First Set", "description": None},
    )
    second_created = user.client.post(
        f"/api/test-sets?workspace_id={second_workspace_id}",
        json={"name": "Second Set", "description": None},
    )
    assert first_created.status_code == 201
    assert second_created.status_code == 201
    _set_last_workspace(user.user_id, second_workspace_id)

    response = user.client.get("/api/test-sets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == second_created.json()["id"]
    assert payload["items"][0]["workspace_id"] == second_workspace_id


def test_multi_membership_without_last_workspace_uses_oldest_membership(
    legacy_workspace_harness: LegacyWorkspaceHarness,
) -> None:
    user = _register(legacy_workspace_harness, "oldest@example.com")
    first_workspace_id = _personal_workspace_id(user.user_id)
    second_workspace_id = create_workspace(user.client, name="Newest Workspace")
    first_created = user.client.post(
        f"/api/test-sets?workspace_id={first_workspace_id}",
        json={"name": "Oldest Set", "description": None},
    )
    second_created = user.client.post(
        f"/api/test-sets?workspace_id={second_workspace_id}",
        json={"name": "Newest Set", "description": None},
    )
    assert first_created.status_code == 201
    assert second_created.status_code == 201
    _set_last_workspace(user.user_id, None)
    earliest = datetime(2025, 1, 1)
    latest = earliest + timedelta(days=1)
    _set_membership_created_at(first_workspace_id, user.user_id, earliest)
    _set_membership_created_at(second_workspace_id, user.user_id, latest)

    response = user.client.get("/api/test-sets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == first_created.json()["id"]
    assert payload["items"][0]["workspace_id"] == first_workspace_id


def test_test_sets_response_diff_is_additive_only(
    legacy_workspace_harness: LegacyWorkspaceHarness,
) -> None:
    user = _register(legacy_workspace_harness, "shape@example.com")
    workspace_id = _personal_workspace_id(user.user_id)
    created = user.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Shape Set", "description": "baseline shape"},
    )
    assert created.status_code == 201
    baseline = {
        "items": [
            {
                "id": created.json()["id"],
                "name": "Shape Set",
                "description": "baseline shape",
                "document_count": 0,
                "created_at": created.json()["created_at"],
                "updated_at": created.json()["updated_at"],
            }
        ],
        "total": 1,
    }

    response = user.client.get("/api/test-sets")

    assert response.status_code == 200
    _assert_contains_baseline(response.json(), baseline)
