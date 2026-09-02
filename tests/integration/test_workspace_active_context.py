from __future__ import annotations

from pathlib import Path

from app.models.db.user_account import UserAccount
from app.repositories.test_set_repository import TestSetRepository as Repository
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)


def _set_fallback(harness: WorkspaceApiHarness, user_id: str, workspace_id: str) -> None:
    with harness.session_factory() as session:
        user = session.get(UserAccount, user_id)
        assert user is not None
        user.last_workspace_id = workspace_id
        session.add(user)
        session.commit()


def test_session_selector_precedence_is_query_then_header_then_fallback(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("precedence@example.com", "Owner")
    fallback_id = create_workspace(owner.client, name="Fallback")
    header_id = create_workspace(owner.client, name="Header")
    query_id = create_workspace(owner.client, name="Query")
    _set_fallback(workspace_api_harness, owner.user_id, fallback_id)

    query_response = owner.client.get(
        f"/api/workspaces/session?workspace_id={query_id}",
        headers={"X-Workspace-Id": header_id},
    )
    header_response = owner.client.get(
        "/api/workspaces/session",
        headers={"X-Workspace-Id": header_id},
    )
    fallback_response = owner.client.get("/api/workspaces/session")

    assert query_response.status_code == 200
    assert query_response.json()["current_workspace"]["id"] == query_id
    assert header_response.status_code == 200
    assert header_response.json()["current_workspace"]["id"] == header_id
    assert fallback_response.status_code == 200
    assert fallback_response.json()["current_workspace"]["id"] == fallback_id


def test_stale_session_selector_falls_back_without_changing_active_workspace(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("stale@example.com", "Owner")
    fallback_id = create_workspace(owner.client, name="Fallback")
    _set_fallback(workspace_api_harness, owner.user_id, fallback_id)

    response = owner.client.get(
        "/api/workspaces/session?workspace_id=ws_stale",
        headers={"X-Workspace-Id": "ws_also_stale"},
    )

    assert response.status_code == 200
    assert response.json()["current_workspace"]["id"] == fallback_id
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        assert user.last_workspace_id == fallback_id


def test_workspace_b_header_cannot_read_workspace_a_legacy_test_set(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("isolation@example.com", "Owner")
    workspace_a_id = create_workspace(owner.client, name="Workspace A")
    workspace_b_id = create_workspace(owner.client, name="Workspace B")
    owner.client.app.state.test_set_repository = Repository()
    created = owner.client.post(
        f"/api/test-sets?workspace_id={workspace_a_id}",
        json={"name": "A only", "description": None},
    )
    assert created.status_code == 201

    response = owner.client.get(
        f"/api/test-sets/{created.json()['id']}",
        headers={"X-Workspace-Id": workspace_b_id},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "RESOURCE_NOT_FOUND"


def test_audit_light_remains_owner_admin_only(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("audit-owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("audit-admin@example.com", "Admin")
    editor = workspace_api_harness.register_user("audit-editor@example.com", "Editor")
    workspace_id = create_workspace(owner.client, name="Audit")
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")
    add_member(owner.client, workspace_id=workspace_id, user_id=editor.user_id, role="editor")

    owner_response = owner.client.get(f"/api/workspaces/{workspace_id}/audit-events")
    admin_response = admin.client.get(f"/api/workspaces/{workspace_id}/audit-events")
    editor_response = editor.client.get(f"/api/workspaces/{workspace_id}/audit-events")

    assert owner_response.status_code == 200
    assert owner_response.json() == {
        "implemented": False,
        "status": "not_implemented",
        "items": [],
        "total": 0,
    }
    assert admin_response.status_code == 200
    assert admin_response.json() == {
        "implemented": False,
        "status": "not_implemented",
        "items": [],
        "total": 0,
    }
    assert editor_response.status_code == 403


def test_legacy_projects_routes_remain_registered() -> None:
    routes_source = (Path(__file__).parents[2] / "frontend/src/app/routes.tsx").read_text(
        encoding="utf-8"
    )

    assert 'path: "projects"' in routes_source
    assert 'path: "projects/:projectId"' in routes_source
