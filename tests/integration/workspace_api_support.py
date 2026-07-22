from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember


async def skip_discover_seed_configs(_: object) -> int:
    return 0


def reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@dataclass(frozen=True, slots=True)
class RegisteredClient:
    client: TestClient
    user_id: str


@dataclass(frozen=True, slots=True)
class WorkspaceApiHarness:
    register_user: Callable[[str, str], RegisteredClient]
    session_factory: Callable[[], Session]


@pytest.fixture()
def workspace_api_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[WorkspaceApiHarness]:
    database_path = tmp_path / "workspace-api.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    clients: list[TestClient] = []

    def register_user(email: str, name: str) -> RegisteredClient:
        client = TestClient(app)
        clients.append(client)
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "StrongerPassword123!",
                "name": name,
            },
        )
        assert response.status_code == 201
        return RegisteredClient(
            client=client,
            user_id=response.json()["data"]["user"]["id"],
        )

    yield WorkspaceApiHarness(register_user=register_user, session_factory=db_session.SessionLocal)

    for client in clients:
        client.close()
    reset_db_runtime()


def create_workspace(client: TestClient, *, name: str = "Workspace A") -> str:
    response = client.post("/api/workspaces", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def add_member(
    client: TestClient,
    *,
    workspace_id: str,
    user_id: str,
    role: str,
    expected_status: int = 201,
) -> TestClient:
    with db_session.SessionLocal() as session:
        user = session.get(UserAccount, user_id)
        assert user is not None
    response = client.post(
        f"/api/workspaces/{workspace_id}/members",
        json={"email": user.email, "role": role},
    )
    assert response.status_code == expected_status
    return response


def assert_workspace_deleted(session_factory: Callable[[], Session], workspace_id: str) -> None:
    with session_factory() as session:
        assert session.get(Workspace, workspace_id) is None
        member_count = session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace_id
            )
        )
        assert member_count == 0


def assert_transfer_result(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    expected_owner_user_id: str,
    expected_admin_user_id: str,
) -> None:
    with session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        assert workspace.owner_user_id == expected_owner_user_id
        memberships = {
            member.user_id: member.role
            for member in session.scalars(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
            )
        }
        assert memberships[expected_owner_user_id] == "owner"
        assert memberships[expected_admin_user_id] == "admin"


def run_concurrent_transfer(
    *,
    workspace_id: str,
    session_cookie: str,
    first_target_user_id: str,
    second_target_user_id: str,
) -> list[int]:
    cookie_name = get_settings().auth_session_cookie_name
    barrier = threading.Barrier(2)
    with TestClient(app) as first_client, TestClient(app) as second_client:
        first_client.cookies.set(cookie_name, session_cookie)
        second_client.cookies.set(cookie_name, session_cookie)

        def attempt_transfer(client: TestClient, target_user_id: str) -> int:
            barrier.wait(timeout=5)
            response = client.post(
                f"/api/workspaces/{workspace_id}/transfer-owner",
                json={"new_owner_user_id": target_user_id},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(attempt_transfer, first_client, first_target_user_id)
            second_future = executor.submit(attempt_transfer, second_client, second_target_user_id)
            return sorted([first_future.result(), second_future.result()])


def assert_single_owner_invariant(
    session_factory: Callable[[], Session], workspace_id: str
) -> None:
    with session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        owner_members = list(
            session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == "owner",
                )
            )
        )
        assert len(owner_members) == 1
        assert workspace.owner_user_id == owner_members[0].user_id
