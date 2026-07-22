from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.models.db.user_account import UserAccount
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    assert_single_owner_invariant,
    assert_transfer_result,
    assert_workspace_deleted,
    create_workspace,
    run_concurrent_transfer,
)

SUMMARY_KEYS = {
    "id",
    "name",
    "description",
    "is_default",
    "role",
    "capabilities",
    "member_count",
    "workflow_count",
    "database_count",
    "provider_count",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _workspace_runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'workspace-api.sqlite3'}"
    provider_db_path = str(tmp_path / "providers.db")
    encryption_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    monkeypatch.setenv("PROVIDER_DB_PATH", provider_db_path)
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("BACKEND_WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("BACKEND_DATABASE_URL", database_url)
    monkeypatch.setenv("BACKEND_PROVIDER_DB_PATH", provider_db_path)
    monkeypatch.setenv("BACKEND_PROVIDER_ENCRYPTION_KEY", encryption_key)


def test_create_workspace_makes_caller_owner_and_lists_members(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")

    response = owner.client.post(
        "/api/workspaces",
        json={"name": "Alpha Workspace", "description": "primary"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {
        "id",
        "name",
        "description",
        "is_default",
        "role",
        "capabilities",
        "member_count",
        "workflow_count",
        "database_count",
        "provider_count",
        "created_at",
        "updated_at",
    }
    assert payload["name"] == "Alpha Workspace"
    assert payload["is_default"] is False
    assert payload["role"] == "owner"
    assert set(payload["capabilities"]) == set(CAPABILITIES[WorkspaceRole.OWNER])
    assert payload["member_count"] == 1
    assert payload["workflow_count"] is None
    assert payload["database_count"] is None
    assert payload["provider_count"] is None

    members_response = owner.client.get(f"/api/workspaces/{payload['id']}/members")
    assert members_response.status_code == 200
    members_payload = members_response.json()
    assert members_payload["total"] == 1
    assert members_payload["items"][0]["user_id"] == owner.user_id
    assert members_payload["items"][0]["role"] == "owner"


def test_list_workspaces_returns_only_caller_memberships(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("outsider@example.com", "Outsider")
    first_workspace_id = create_workspace(owner.client, name="First Workspace")
    second_workspace_id = create_workspace(owner.client, name="Second Workspace")
    outsider_workspace_id = create_workspace(outsider.client, name="Outsider Workspace")
    assert owner.client.post(f"/api/workspaces/{first_workspace_id}/switch").status_code == 200

    response = owner.client.get("/api/workspaces")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    returned_ids = {item["id"] for item in payload["items"]}
    assert {first_workspace_id, second_workspace_id} <= returned_ids
    assert outsider_workspace_id not in returned_ids
    summaries = {item["id"]: item for item in payload["items"]}
    assert all(set(item) == SUMMARY_KEYS for item in payload["items"])
    assert summaries[first_workspace_id]["role"] == "owner"
    assert summaries[first_workspace_id]["is_default"] is True
    assert summaries[second_workspace_id]["is_default"] is False
    assert set(summaries[first_workspace_id]["capabilities"]) == set(
        CAPABILITIES[WorkspaceRole.OWNER]
    )


def test_switch_workspace_updates_last_workspace_id(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client)

    response = owner.client.post(f"/api/workspaces/{workspace_id}/switch")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"current_workspace", "memberships", "capabilities"}
    assert payload["current_workspace"]["id"] == workspace_id
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        assert user.last_workspace_id == workspace_id


def test_admin_can_add_member(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("admin@example.com", "Admin")
    editor = workspace_api_harness.register_user("editor@example.com", "Editor")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")

    response = add_member(
        admin.client,
        workspace_id=workspace_id,
        user_id=editor.user_id,
        role="editor",
    )

    payload = response.json()
    assert payload["user_id"] == editor.user_id
    assert payload["email"] == "editor@example.com"
    assert payload["role"] == "editor"
    assert payload["status"] == "active"


def test_admin_cannot_add_owner_member(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("admin@example.com", "Admin")
    candidate = workspace_api_harness.register_user("candidate@example.com", "Candidate")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")

    response = add_member(
        admin.client,
        workspace_id=workspace_id,
        user_id=candidate.user_id,
        role="owner",
        expected_status=409,
    )

    assert response.json()["error_code"] == "REQUEST_CONFLICT"
    assert_single_owner_invariant(workspace_api_harness.session_factory, workspace_id)


def test_editor_cannot_add_member(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    editor = workspace_api_harness.register_user("editor@example.com", "Editor")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=editor.user_id, role="editor")

    response = add_member(
        editor.client,
        workspace_id=workspace_id,
        user_id=viewer.user_id,
        role="viewer",
        expected_status=403,
    )

    assert response.json()["error_code"] == "REQUIRED_CAPABILITY_MISSING"


def test_remove_member_succeeds_for_admin_or_owner(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("admin@example.com", "Admin")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")
    add_member(owner.client, workspace_id=workspace_id, user_id=viewer.user_id, role="viewer")

    response = admin.client.delete(f"/api/workspaces/{workspace_id}/members/{viewer.user_id}")

    assert response.status_code == 204
    members_response = owner.client.get(f"/api/workspaces/{workspace_id}/members")
    assert members_response.status_code == 200
    member_ids = {item["user_id"] for item in members_response.json()["items"]}
    assert member_ids == {owner.user_id, admin.user_id}


def test_remove_last_owner_is_refused(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client)

    response = owner.client.delete(f"/api/workspaces/{workspace_id}/members/{owner.user_id}")

    assert response.status_code == 409
    assert response.json()["error_code"] == "REQUEST_CONFLICT"


def test_transfer_owner_promotes_target_and_demotes_caller(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("admin@example.com", "Admin")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")
    assert owner.client.post(f"/api/workspaces/{workspace_id}/switch").status_code == 200

    response = owner.client.post(
        f"/api/workspaces/{workspace_id}/transfer-owner",
        json={"new_owner_user_id": admin.user_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == SUMMARY_KEYS
    assert payload["id"] == workspace_id
    assert payload["is_default"] is True
    assert payload["role"] == "admin"
    assert set(payload["capabilities"]) == set(CAPABILITIES[WorkspaceRole.ADMIN])
    assert payload["member_count"] == 2
    assert_transfer_result(
        workspace_api_harness.session_factory,
        workspace_id=workspace_id,
        expected_owner_user_id=admin.user_id,
        expected_admin_user_id=owner.user_id,
    )


def test_transfer_owner_rejects_admin_actor(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("admin@example.com", "Admin")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=admin.user_id, role="admin")

    response = admin.client.post(
        f"/api/workspaces/{workspace_id}/transfer-owner",
        json={"new_owner_user_id": owner.user_id},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "WORKSPACE_FORBIDDEN"


def test_transfer_owner_rejects_non_member_target(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client)

    response = owner.client.post(
        f"/api/workspaces/{workspace_id}/transfer-owner",
        json={"new_owner_user_id": outsider.user_id},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "REQUEST_CONFLICT"


def test_delete_workspace_refuses_while_other_members_exist(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=viewer.user_id, role="viewer")

    response = owner.client.delete(f"/api/workspaces/{workspace_id}")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "WORKSPACE_NOT_EMPTY"
    assert payload["details"]["counts"]["members_excluding_owner"] == 1


def test_delete_workspace_succeeds_after_removing_other_members(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=viewer.user_id, role="viewer")
    remove_response = owner.client.delete(
        f"/api/workspaces/{workspace_id}/members/{viewer.user_id}"
    )
    assert remove_response.status_code == 204

    response = owner.client.delete(f"/api/workspaces/{workspace_id}")

    assert response.status_code == 204
    assert_workspace_deleted(workspace_api_harness.session_factory, workspace_id)


def test_concurrent_transfer_keeps_single_owner_invariant(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    first_target = workspace_api_harness.register_user("first@example.com", "First")
    second_target = workspace_api_harness.register_user("second@example.com", "Second")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=first_target.user_id, role="admin")
    add_member(owner.client, workspace_id=workspace_id, user_id=second_target.user_id, role="admin")

    session_cookie = owner.client.cookies.get(get_settings().auth_session_cookie_name)
    assert session_cookie is not None
    statuses = run_concurrent_transfer(
        workspace_id=workspace_id,
        session_cookie=session_cookie,
        first_target_user_id=first_target.user_id,
        second_target_user_id=second_target.user_id,
    )

    assert statuses == [200, 403]
    assert_single_owner_invariant(workspace_api_harness.session_factory, workspace_id)
