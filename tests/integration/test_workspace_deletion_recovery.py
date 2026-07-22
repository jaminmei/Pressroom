from __future__ import annotations

from sqlalchemy import select

from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from tests.integration.workspace_api_support import WorkspaceApiHarness, create_workspace


def test_removing_last_active_membership_repairs_user_fallback(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("recovery-owner@example.com", "Owner")
    admin = workspace_api_harness.register_user("recovery-admin@example.com", "Admin")
    fallback_id = create_workspace(admin.client, name="Fallback")
    workspace_id = create_workspace(owner.client, name="Remove me")
    with workspace_api_harness.session_factory() as session:
        session.add(
            WorkspaceMember(
                id="wsm_recovery",
                workspace_id=workspace_id,
                user_id=admin.user_id,
                role="admin",
                created_at=session.scalar(
                    select(Workspace.created_at).where(Workspace.id == workspace_id)
                ),
            )
        )
        user = session.get(UserAccount, admin.user_id)
        assert user is not None
        user.last_workspace_id = workspace_id
        session.commit()

    response = owner.client.delete(f"/api/workspaces/{workspace_id}/members/{admin.user_id}")

    assert response.status_code == 204
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, admin.user_id)
        assert user is not None
        assert user.last_workspace_id != workspace_id
        assert user.last_workspace_id in {fallback_id, f"ws_personal_{admin.user_id}"}
