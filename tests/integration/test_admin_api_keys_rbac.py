from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.api.admin.api_keys import router as admin_api_keys_router
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthUser
from app.models.db.api_key import ApiKey
from app.models.workflow import WorkflowDefinition
from app.services.api_key_service import ApiKeyService
from app.services.database_workflow_store import DatabaseWorkflowStore
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


def _sample_definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
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
    )


def _reset_db_runtime() -> None:
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture()
def admin_api_keys_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[FastAPI]:
    database_path = tmp_path / "admin-api-keys-rbac.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    enable_rbac(monkeypatch)
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    app = FastAPI()
    app.include_router(admin_api_keys_router)
    app.state.api_key_service = ApiKeyService()
    yield app
    app.dependency_overrides.clear()


def test_issue_api_key_uses_workflow_workspace_rbac(admin_api_keys_app: FastAPI) -> None:
    session_factory = db_session.SessionLocal
    owner_user_id = make_user(session_factory, "owner@example.com")
    editor_user_id = make_user(session_factory, "editor@example.com")
    cross_owner_user_id = make_user(session_factory, "cross-owner@example.com")

    owner_workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=owner_user_id,
        member_role=WorkspaceRole.OWNER,
    )
    cross_workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=cross_owner_user_id,
        member_role=WorkspaceRole.OWNER,
    )

    with session_factory() as session:
        from app.models.db.workspace_member import WorkspaceMember

        session.add(
            WorkspaceMember(
                id="wsm_editor_owner_workspace",
                workspace_id=owner_workspace_id,
                user_id=editor_user_id,
                role=WorkspaceRole.EDITOR.value,
            )
        )
        session.commit()

    store = DatabaseWorkflowStore(session_factory=session_factory)
    owner_workflow = store.create(
        name="Owner workflow",
        definition=_sample_definition(),
        workspace_id=owner_workspace_id,
    )
    cross_workflow = store.create(
        name="Cross workflow",
        definition=_sample_definition(),
        workspace_id=cross_workspace_id,
    )

    owner_user = AuthUser(id=owner_user_id, email="owner@example.com")
    editor_user = AuthUser(id=editor_user_id, email="editor@example.com")
    cross_owner_user = AuthUser(id=cross_owner_user_id, email="cross-owner@example.com")

    with make_workspace_client(
        admin_api_keys_app,
        user=owner_user,
        workspace_id=owner_workspace_id,
        role=WorkspaceRole.OWNER,
    ) as owner_client:
        empty_response = owner_client.get(
            f"/api/admin/api-keys?workflow_id={owner_workflow.id}&include_inactive=false"
        )
        owner_response = owner_client.post(
            "/api/admin/api-keys",
            json={"workflow_id": owner_workflow.id, "description": "Owner can issue"},
        )
        assert owner_response.status_code == 201
        active_response = owner_client.get(
            f"/api/admin/api-keys?workflow_id={owner_workflow.id}&include_inactive=false"
        )
        revoke_response = owner_client.post(
            f"/api/admin/api-keys/{owner_response.json()['id']}/revoke"
        )
        inactive_filtered_response = owner_client.get(
            f"/api/admin/api-keys?workflow_id={owner_workflow.id}&include_inactive=false"
        )
        inactive_included_response = owner_client.get(
            f"/api/admin/api-keys?workflow_id={owner_workflow.id}&include_inactive=true"
        )

    assert empty_response.status_code == 200
    assert empty_response.json()["meta"]["total"] == 0
    assert owner_response.status_code == 201
    owner_payload = owner_response.json()
    assert owner_payload["workflow_id"] == owner_workflow.id
    assert owner_payload["key"].startswith("dca_")
    assert active_response.status_code == 200
    assert active_response.json()["meta"]["total"] == 1
    assert active_response.json()["data"] == [
        {
            "id": owner_payload["id"],
            "key_prefix": owner_payload["key_prefix"],
            "workflow_id": owner_workflow.id,
            "description": "Owner can issue",
            "is_active": True,
            "created_at": owner_payload["created_at"],
            "last_used_at": None,
            "expires_at": None,
        }
    ]
    assert revoke_response.status_code == 200
    assert revoke_response.json() == {"id": owner_payload["id"], "is_active": False}
    assert inactive_filtered_response.status_code == 200
    assert inactive_filtered_response.json()["meta"]["total"] == 0
    assert inactive_included_response.status_code == 200
    assert inactive_included_response.json()["meta"]["total"] == 1
    assert inactive_included_response.json()["data"][0]["is_active"] is False
    with session_factory() as session:
        issued_key = session.scalar(select(ApiKey).where(ApiKey.id == owner_payload["id"]))
        assert issued_key is not None
        assert issued_key.created_by == owner_user_id

    second_owner_workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=owner_user_id,
        member_role=WorkspaceRole.OWNER,
    )
    with make_workspace_client(
        admin_api_keys_app,
        user=owner_user,
        workspace_id=second_owner_workspace_id,
        role=WorkspaceRole.OWNER,
    ) as second_workspace_client:
        active_list = second_workspace_client.get("/api/admin/api-keys")
        cross_issue = second_workspace_client.post(
            "/api/admin/api-keys",
            json={"workflow_id": owner_workflow.id, "description": "Wrong active workspace"},
        )
        cross_revoke = second_workspace_client.post(
            f"/api/admin/api-keys/{owner_payload['id']}/revoke"
        )

    assert active_list.status_code == 200
    assert active_list.json()["meta"]["total"] == 0
    assert cross_issue.status_code == 404
    assert cross_revoke.status_code == 404

    with make_workspace_client(
        admin_api_keys_app,
        user=editor_user,
        workspace_id=owner_workspace_id,
        role=WorkspaceRole.EDITOR,
    ) as editor_client:
        editor_response = editor_client.post(
            "/api/admin/api-keys",
            json={"workflow_id": owner_workflow.id, "description": "Editor blocked"},
        )

    assert editor_response.status_code == 403
    assert editor_response.json()["detail"] == "api_key.manage required"

    with make_workspace_client(
        admin_api_keys_app,
        user=cross_owner_user,
        workspace_id=cross_workspace_id,
        role=WorkspaceRole.OWNER,
    ) as cross_owner_client:
        cross_owner_response = cross_owner_client.post(
            "/api/admin/api-keys",
            json={"workflow_id": owner_workflow.id, "description": "Cross workspace hidden"},
        )
        hidden_response = cross_owner_client.post(
            "/api/admin/api-keys",
            json={"workflow_id": cross_workflow.id, "description": "Own workspace visible"},
        )

    assert cross_owner_response.status_code == 404
    assert cross_owner_response.json()["detail"] == f"Workflow not found: {owner_workflow.id}"
    assert hidden_response.status_code == 201
