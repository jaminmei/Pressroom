from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)

SESSION_KEYS = {"current_workspace", "memberships", "capabilities"}
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
MEMBER_KEYS = {
    "user_id",
    "email",
    "name",
    "role",
    "status",
    "joined_at",
    "invited_at",
    "last_active_at",
    "is_current_user",
}
CAPABILITY_FIXTURE = json.loads(
    (Path(__file__).parents[2] / "frontend/src/contracts/workspace-permission-v1.json").read_text()
)


def test_backend_capabilities_match_shared_frontend_fixture() -> None:
    # Given the canonical backend role matrix and shared cross-language fixture
    canonical = set().union(*CAPABILITIES.values())

    # When capability vocabularies are compared
    # Then the fixture names every raw backend capability exactly once
    assert set(CAPABILITY_FIXTURE["backend_capabilities"]) == canonical
    assert set(CAPABILITY_FIXTURE["derivations"]) == canonical
    assert CAPABILITY_FIXTURE["authenticated_global"] == ["workspace.create"]


def test_session_returns_exact_caller_scoped_contract(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("outsider@example.com", "Outsider")
    shared_workspace_id = create_workspace(owner.client, name="Shared")
    outsider_workspace_id = create_workspace(outsider.client, name="Outsider only")

    # When
    response = owner.client.get("/api/workspaces/session")

    # Then
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == SESSION_KEYS
    assert set(payload["current_workspace"]) == SUMMARY_KEYS
    assert all(
        set(item) == {"workspace", "role", "capabilities", "joined_at"}
        for item in payload["memberships"]
    )
    assert all(set(item["workspace"]) == SUMMARY_KEYS for item in payload["memberships"])
    returned_ids = {item["workspace"]["id"] for item in payload["memberships"]}
    assert shared_workspace_id in returned_ids
    assert outsider_workspace_id not in returned_ids
    assert payload["current_workspace"]["member_count"] == 1
    assert payload["current_workspace"]["workflow_count"] == 0
    assert payload["current_workspace"]["database_count"] == 0
    assert payload["current_workspace"]["provider_count"] is None


def test_session_auto_creates_personal_workspace_for_user_without_memberships(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    user = workspace_api_harness.register_user("fresh@example.com", "Fresh")
    with workspace_api_harness.session_factory() as session:
        membership_ids = list(
            session.scalars(
                select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.user_id)
            )
        )
        session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.user_id))
        session.execute(delete(Workspace).where(Workspace.id.in_(membership_ids)))
        session.commit()

    # When
    response = user.client.get("/api/workspaces/session")

    # Then
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_workspace"]["id"] == f"ws_personal_{user.user_id}"
    assert len(payload["memberships"]) == 1


def test_session_with_cleared_selection_chooses_oldest_membership(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("oldest@example.com", "Oldest")
    create_workspace(owner.client, name="Newer")
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        user.last_workspace_id = None
        session.commit()
        oldest_workspace_id = session.scalar(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == owner.user_id)
            .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.workspace_id.asc())
        )

    # When
    response = owner.client.get("/api/workspaces/session")

    # Then
    assert response.status_code == 200
    assert response.json()["current_workspace"]["id"] == oldest_workspace_id
    assert response.json()["current_workspace"]["is_default"] is True


def test_session_repairs_stale_selection_after_membership_revocation(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("repair@example.com", "Repair")
    revoked_workspace_id = create_workspace(owner.client, name="Revoked")
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        user.last_workspace_id = revoked_workspace_id
        session.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.user_id == owner.user_id,
                WorkspaceMember.workspace_id == revoked_workspace_id,
            )
        )
        session.commit()

    # When
    response = owner.client.get("/api/workspaces/session")

    # Then
    assert response.status_code == 200
    payload = response.json()
    returned_ids = {item["workspace"]["id"] for item in payload["memberships"]}
    assert revoked_workspace_id not in returned_ids
    assert payload["current_workspace"]["id"] in returned_ids
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        assert user.last_workspace_id == payload["current_workspace"]["id"]


def test_session_uses_canonical_capabilities_for_all_roles(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("roles-owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client, name="Roles")
    clients_by_role = {WorkspaceRole.OWNER: owner}
    for role in (
        WorkspaceRole.ADMIN,
        WorkspaceRole.EDITOR,
        WorkspaceRole.RUNNER,
        WorkspaceRole.VIEWER,
    ):
        member = workspace_api_harness.register_user(f"{role.value}@example.com", role.value)
        add_member(owner.client, workspace_id=workspace_id, user_id=member.user_id, role=role.value)
        clients_by_role[role] = member

    # When / Then
    for role, member in clients_by_role.items():
        switch_response = member.client.post(f"/api/workspaces/{workspace_id}/switch")
        assert switch_response.status_code == 200
        payload = switch_response.json()
        assert set(payload) == SESSION_KEYS
        assert payload["current_workspace"]["id"] == workspace_id
        assert set(payload["capabilities"]) == set(CAPABILITIES[role])
        assert set(payload["current_workspace"]["capabilities"]) == set(CAPABILITIES[role])


def test_switch_returns_full_session_and_outsider_gets_404(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("switch-owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("switch-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client, name="Switch target")

    # When
    success = owner.client.post(f"/api/workspaces/{workspace_id}/switch")
    denied = outsider.client.post(f"/api/workspaces/{workspace_id}/switch")

    # Then
    assert success.status_code == 200
    assert set(success.json()) == SESSION_KEYS
    assert success.json()["current_workspace"]["id"] == workspace_id
    assert success.json()["current_workspace"]["is_default"] is True
    assert denied.status_code == 404


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_workspace_settings_patch_updates_fields_and_default(
    workspace_api_harness: WorkspaceApiHarness,
    role: str,
) -> None:
    owner = workspace_api_harness.register_user(f"settings-{role}-owner@example.com", "Owner")
    actor = owner
    workspace_id = create_workspace(owner.client, name="Before")
    if role == "admin":
        actor = workspace_api_harness.register_user("settings-admin@example.com", "Admin")
        add_member(owner.client, workspace_id=workspace_id, user_id=actor.user_id, role=role)

    response = actor.client.patch(
        f"/api/workspaces/{workspace_id}",
        json={"name": "After", "description": "Updated", "is_default": True},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "After"
    assert response.json()["description"] == "Updated"
    assert response.json()["is_default"] is True
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, actor.user_id)
        assert user is not None
        assert user.last_workspace_id == workspace_id


def test_workspace_settings_patch_false_is_rejected_and_permissions_are_hidden(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("settings-owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("settings-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client)
    denied_clients = []
    for role in ("editor", "runner", "viewer"):
        member = workspace_api_harness.register_user(f"settings-{role}@example.com", role)
        add_member(owner.client, workspace_id=workspace_id, user_id=member.user_id, role=role)
        denied_clients.append(member.client)

    default_response = owner.client.patch(
        f"/api/workspaces/{workspace_id}", json={"is_default": True}
    )
    false_response = owner.client.patch(
        f"/api/workspaces/{workspace_id}", json={"is_default": False}
    )
    denied_statuses = [
        client.patch(f"/api/workspaces/{workspace_id}", json={"name": "Denied"}).status_code
        for client in denied_clients
    ]
    outsider_status = outsider.client.patch(
        f"/api/workspaces/{workspace_id}", json={"name": "Hidden"}
    ).status_code

    assert default_response.status_code == 200
    assert false_response.status_code == 409
    assert denied_statuses == [403, 403, 403]
    assert outsider_status == 404


def test_member_list_returns_enriched_shape_to_every_role(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("members-owner@example.com", "Owner Name")
    outsider = workspace_api_harness.register_user("members-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client)
    clients = [owner.client]
    for role in ("admin", "editor", "runner", "viewer"):
        member = workspace_api_harness.register_user(f"members-{role}@example.com", role.title())
        add_member(owner.client, workspace_id=workspace_id, user_id=member.user_id, role=role)
        clients.append(member.client)

    responses = [client.get(f"/api/workspaces/{workspace_id}/members") for client in clients]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200]
    owner_payload = responses[0].json()["items"][0]
    assert set(owner_payload) == MEMBER_KEYS
    assert owner_payload == {
        "user_id": owner.user_id,
        "email": "members-owner@example.com",
        "name": "Owner Name",
        "role": "owner",
        "status": "active",
        "joined_at": owner_payload["joined_at"],
        "invited_at": None,
        "last_active_at": None,
        "is_current_user": True,
    }
    assert outsider.client.get(f"/api/workspaces/{workspace_id}/members").status_code == 404


def test_member_add_by_normalized_email_returns_enriched_contract(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("add-owner@example.com", "Owner")
    target = workspace_api_harness.register_user("target@example.com", "Target Name")
    workspace_id = create_workspace(owner.client)

    response = owner.client.post(
        f"/api/workspaces/{workspace_id}/members",
        json={"email": "  TARGET@EXAMPLE.COM ", "role": "viewer"},
    )

    assert response.status_code == 201
    assert set(response.json()) == MEMBER_KEYS
    assert response.json()["user_id"] == target.user_id
    assert response.json()["name"] == "Target Name"
    assert response.json()["is_current_user"] is False


def test_member_add_rejects_non_string_email_with_422(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("typed-email-owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client)

    # When
    response = owner.client.post(
        f"/api/workspaces/{workspace_id}/members",
        json={"email": 123, "role": "viewer"},
    )

    # Then
    assert response.status_code == 422


@pytest.mark.parametrize("workspace_exists", [True, False])
def test_non_member_gets_404_regardless_of_workspace_existence(
    workspace_api_harness: WorkspaceApiHarness,
    workspace_exists: bool,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("hidden-owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("hidden-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client) if workspace_exists else "ws_missing"

    # When
    response = outsider.client.get(f"/api/workspaces/{workspace_id}/members")

    # Then
    assert response.status_code == 404


def test_transfer_owner_hides_target_user_from_outsiders(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    # Given
    owner = workspace_api_harness.register_user("transfer-owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("transfer-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client)

    # When
    existing_target = outsider.client.post(
        f"/api/workspaces/{workspace_id}/transfer-owner",
        json={"new_owner_user_id": owner.user_id},
    )
    missing_target = outsider.client.post(
        f"/api/workspaces/{workspace_id}/transfer-owner",
        json={"new_owner_user_id": "usr_missing"},
    )

    # Then
    assert existing_target.status_code == 404
    assert missing_target.status_code == 404


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"email": "missing@example.com", "role": "viewer"}, 404),
        ({"email": "not-an-email", "role": "viewer"}, 422),
        ({"email": "candidate@example.com", "role": "owner"}, 409),
    ],
)
def test_member_add_rejects_invalid_targets(
    workspace_api_harness: WorkspaceApiHarness,
    payload: dict[str, str],
    expected_status: int,
) -> None:
    owner = workspace_api_harness.register_user("reject-owner@example.com", "Owner")
    workspace_api_harness.register_user("candidate@example.com", "Candidate")
    workspace_id = create_workspace(owner.client)

    response = owner.client.post(f"/api/workspaces/{workspace_id}/members", json=payload)

    assert response.status_code == expected_status


def test_member_add_rejects_duplicate_and_lower_roles(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("duplicate-owner@example.com", "Owner")
    target = workspace_api_harness.register_user("duplicate@example.com", "Target")
    editor = workspace_api_harness.register_user("duplicate-editor@example.com", "Editor")
    workspace_id = create_workspace(owner.client)
    add_member(owner.client, workspace_id=workspace_id, user_id=target.user_id, role="viewer")
    add_member(owner.client, workspace_id=workspace_id, user_id=editor.user_id, role="editor")

    duplicate = owner.client.post(
        f"/api/workspaces/{workspace_id}/members",
        json={"email": "duplicate@example.com", "role": "viewer"},
    )
    denied = editor.client.post(
        f"/api/workspaces/{workspace_id}/members",
        json={"email": "missing@example.com", "role": "viewer"},
    )

    assert duplicate.status_code == 409
    assert denied.status_code == 403


def test_member_role_patch_returns_enriched_contract_and_enforces_guards(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("role-owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("role-admin@example.com", "Admin")
    target = workspace_api_harness.register_user("role-target@example.com", "Target")
    editor = workspace_api_harness.register_user("role-editor@example.com", "Editor")
    workspace_id = create_workspace(owner.client)
    for member, role in ((admin, "admin"), (target, "viewer"), (editor, "editor")):
        add_member(owner.client, workspace_id=workspace_id, user_id=member.user_id, role=role)

    success = admin.client.patch(
        f"/api/workspaces/{workspace_id}/members/{target.user_id}", json={"role": "runner"}
    )
    owner_role = owner.client.patch(
        f"/api/workspaces/{workspace_id}/members/{target.user_id}", json={"role": "owner"}
    )
    lower_role = editor.client.patch(
        f"/api/workspaces/{workspace_id}/members/{target.user_id}", json={"role": "viewer"}
    )
    missing = owner.client.patch(
        f"/api/workspaces/{workspace_id}/members/usr_missing", json={"role": "viewer"}
    )
    self_demotion = owner.client.patch(
        f"/api/workspaces/{workspace_id}/members/{owner.user_id}", json={"role": "admin"}
    )

    assert success.status_code == 200
    assert set(success.json()) == MEMBER_KEYS
    assert success.json()["role"] == "runner"
    assert owner_role.status_code == 409
    assert lower_role.status_code == 403
    assert missing.status_code == 404
    assert self_demotion.status_code == 409


def test_audit_endpoint_uses_settings_permission_and_empty_contract(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("audit-owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("audit-outsider@example.com", "Outsider")
    workspace_id = create_workspace(owner.client)
    clients_by_role = {"owner": owner.client}
    for role in ("admin", "editor", "runner", "viewer"):
        member = workspace_api_harness.register_user(f"audit-{role}@example.com", role)
        add_member(owner.client, workspace_id=workspace_id, user_id=member.user_id, role=role)
        clients_by_role[role] = member.client

    statuses = {
        role: client.get(f"/api/workspaces/{workspace_id}/audit-events").status_code
        for role, client in clients_by_role.items()
    }

    assert statuses == {"owner": 200, "admin": 200, "editor": 403, "runner": 403, "viewer": 403}
    assert owner.client.get(f"/api/workspaces/{workspace_id}/audit-events").json() == {
        "implemented": False,
        "status": "not_implemented",
        "items": [],
        "total": 0,
    }
    assert outsider.client.get(f"/api/workspaces/{workspace_id}/audit-events").status_code == 404
