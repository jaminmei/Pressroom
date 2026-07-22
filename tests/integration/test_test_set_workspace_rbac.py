from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.test_set import TestSet as TestSetModel
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole
from tests.integration.workspace_api_support import (
    RegisteredClient,
    add_member,
    create_workspace,
    skip_discover_seed_configs,
)


@dataclass(frozen=True, slots=True)
class RbacHarness:
    stack: ExitStack


@pytest.fixture()
def test_set_rbac_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[RbacHarness]:
    database_path = tmp_path / "test-set-workspace-rbac.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    provider_db_path = tmp_path / "providers.sqlite3"
    provider_key = Fernet.generate_key().decode()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("BACKEND_DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("BACKEND_WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(provider_db_path))
    monkeypatch.setenv("BACKEND_PROVIDER_DB_PATH", str(provider_db_path))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", provider_key)
    monkeypatch.setenv("BACKEND_PROVIDER_ENCRYPTION_KEY", provider_key)
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())

    with ExitStack() as stack:
        yield RbacHarness(stack=stack)


def _register(harness: RbacHarness, email: str) -> RegisteredClient:
    client = harness.stack.enter_context(TestClient(app))
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongerPassword123!", "name": email},
    )
    assert response.status_code == 201
    return RegisteredClient(client=client, user_id=response.json()["data"]["user"]["id"])


def _switch(client: TestClient, workspace_id: str) -> None:
    response = client.post(f"/api/workspaces/{workspace_id}/switch")
    assert response.status_code == 200


def _add_member_directly(workspace_id: str, user_id: str, role: WorkspaceRole) -> None:
    with db_session.SessionLocal() as session:
        session.add(
            WorkspaceMember(
                id=f"wsm_{uuid4()}",
                workspace_id=workspace_id,
                user_id=user_id,
                role=role.value,
            )
        )
        session.commit()


def test_owner_and_editor_can_create_test_sets(test_set_rbac_harness: RbacHarness) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    editor = _register(test_set_rbac_harness, "editor@example.com")
    workspace_id = create_workspace(owner.client)
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=editor.user_id,
        role=WorkspaceRole.EDITOR.value,
    )
    _switch(editor.client, workspace_id)

    owner_response = owner.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Owner Set", "description": None},
    )
    editor_response = editor.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Editor Set", "description": None},
    )

    assert owner_response.status_code == 201
    assert editor_response.status_code == 201
    assert owner_response.json()["workspace_id"] == workspace_id
    assert editor_response.json()["workspace_id"] == workspace_id


def test_viewer_and_runner_cannot_create_test_sets(
    test_set_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    viewer = _register(test_set_rbac_harness, "viewer@example.com")
    runner = _register(test_set_rbac_harness, "runner@example.com")
    workspace_id = create_workspace(owner.client)
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=viewer.user_id,
        role=WorkspaceRole.VIEWER.value,
    )
    _add_member_directly(workspace_id, runner.user_id, WorkspaceRole.RUNNER)
    _switch(viewer.client, workspace_id)
    _switch(runner.client, workspace_id)

    viewer_response = viewer.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Viewer Set", "description": None},
    )
    runner_response = runner.client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "Runner Set", "description": None},
    )

    assert viewer_response.status_code == 403
    assert runner_response.status_code == 403
    assert viewer_response.json()["details"]["required_capability"] == "dataset.create"
    assert runner_response.json()["details"]["required_capability"] == "dataset.create"


def test_cross_workspace_get_returns_404(test_set_rbac_harness: RbacHarness) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    first_workspace_id = create_workspace(owner.client, name="First")
    second_workspace_id = create_workspace(owner.client, name="Second")
    created = owner.client.post(
        f"/api/test-sets?workspace_id={first_workspace_id}",
        json={"name": "Private Set", "description": None},
    )
    assert created.status_code == 201

    response = owner.client.get(
        f"/api/test-sets/{created.json()['id']}?workspace_id={second_workspace_id}"
    )

    assert response.status_code == 404


def test_create_without_workspace_id_uses_default_workspace(
    test_set_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    workspace_id = create_workspace(owner.client)
    _switch(owner.client, workspace_id)

    response = owner.client.post(
        "/api/test-sets",
        json={"name": "Default Workspace Set", "description": None},
    )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == workspace_id


def test_list_filters_by_workspace(test_set_rbac_harness: RbacHarness) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    first_workspace_id = create_workspace(owner.client, name="First")
    second_workspace_id = create_workspace(owner.client, name="Second")
    first = owner.client.post(
        f"/api/test-sets?workspace_id={first_workspace_id}",
        json={"name": "First Set", "description": None},
    )
    second = owner.client.post(
        f"/api/test-sets?workspace_id={second_workspace_id}",
        json={"name": "Second Set", "description": None},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    response = owner.client.get(f"/api/test-sets?workspace_id={first_workspace_id}")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {first.json()["id"]}


def test_update_and_delete_are_workspace_scoped(
    test_set_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_set_rbac_harness, "owner@example.com")
    first_workspace_id = create_workspace(owner.client, name="First")
    second_workspace_id = create_workspace(owner.client, name="Second")
    created = owner.client.post(
        f"/api/test-sets?workspace_id={first_workspace_id}",
        json={"name": "Scoped Set", "description": None},
    )
    test_set_id = created.json()["id"]

    update_response = owner.client.patch(
        f"/api/test-sets/{test_set_id}?workspace_id={second_workspace_id}",
        json={"name": "Leaked"},
    )
    delete_response = owner.client.delete(
        f"/api/test-sets/{test_set_id}?workspace_id={second_workspace_id}"
    )

    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    with db_session.SessionLocal() as session:
        record = session.get(TestSetModel, test_set_id)
        assert record is not None
        assert record.name == "Scoped Set"
