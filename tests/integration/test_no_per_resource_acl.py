from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import workflows as workflow_api
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.auth import AuthUser
from app.models.workflow import Workflow, WorkflowDefinition
from app.services.database_workflow_store import DatabaseWorkflowStore
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    workflow_api.get_workflow_store.cache_clear()


def _sample_definition() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }


@dataclass(frozen=True, slots=True)
class NoPerResourceAclHarness:
    workspace_id: str
    owner: AuthUser
    editor: AuthUser
    viewer: AuthUser
    session_factory: Callable[[], Session]

    def client(self, user: AuthUser, role: WorkspaceRole) -> TestClient:
        return make_workspace_client(
            app,
            user=user,
            workspace_id=self.workspace_id,
            role=role,
        )

    def create_workflow(self) -> Workflow:
        return DatabaseWorkflowStore(session_factory=self.session_factory).create(
            name="Workspace Workflow",
            definition=WorkflowDefinition.model_validate(_sample_definition()),
            workspace_id=self.workspace_id,
        )


@pytest.fixture()
def no_per_resource_acl_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[NoPerResourceAclHarness]:
    database_path = tmp_path / "no-per-resource-acl.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    enable_rbac(monkeypatch)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", lambda *_args, **_kwargs: 0)
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    session_factory = db_session.SessionLocal
    owner_id = make_user(session_factory, "owner@example.com")
    workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    editor_id = make_user(session_factory, "editor@example.com")
    viewer_id = make_user(session_factory, "viewer@example.com")
    with session_factory() as session:
        from app.models.db.workspace_member import WorkspaceMember

        session.add(
            WorkspaceMember(
                id="wsm_editor",
                workspace_id=workspace_id,
                user_id=editor_id,
                role=WorkspaceRole.EDITOR.value,
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_viewer",
                workspace_id=workspace_id,
                user_id=viewer_id,
                role=WorkspaceRole.VIEWER.value,
            )
        )
        session.commit()

    yield NoPerResourceAclHarness(
        workspace_id=workspace_id,
        owner=AuthUser(id=owner_id, email="owner@example.com"),
        editor=AuthUser(id=editor_id, email="editor@example.com"),
        viewer=AuthUser(id=viewer_id, email="viewer@example.com"),
        session_factory=session_factory,
    )

    app.dependency_overrides.clear()
    workflow_api.get_workflow_store.cache_clear()


def test_viewer_can_read_any_workflow_in_workspace(
    no_per_resource_acl_harness: NoPerResourceAclHarness,
) -> None:
    workflow = no_per_resource_acl_harness.create_workflow()

    with no_per_resource_acl_harness.client(
        no_per_resource_acl_harness.viewer, WorkspaceRole.VIEWER
    ) as client:
        response = client.get(f"/api/workflows/{workflow.id}")

    assert response.status_code == 200
    assert response.json()["id"] == workflow.id


def test_editor_can_edit_any_workflow_in_workspace(
    no_per_resource_acl_harness: NoPerResourceAclHarness,
) -> None:
    workflow = no_per_resource_acl_harness.create_workflow()

    with no_per_resource_acl_harness.client(
        no_per_resource_acl_harness.editor, WorkspaceRole.EDITOR
    ) as client:
        response = client.patch(
            f"/api/workflows/{workflow.id}",
            json={"name": "Edited by workspace editor"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Edited by workspace editor"
