from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_workspace_id() -> str:
    return f"ws_{uuid4()}"


def new_workspace_member_id() -> str:
    return f"wsm_{uuid4()}"


def serialize_workspace(workspace: Workspace) -> dict[str, object]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "description": workspace.description,
        "owner_user_id": workspace.owner_user_id,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }


def serialize_member(member: WorkspaceMember) -> dict[str, object]:
    return {
        "id": member.id,
        "workspace_id": member.workspace_id,
        "user_id": member.user_id,
        "role": member.role,
        "created_at": member.created_at.isoformat(),
    }


def serialize_member_enriched(
    session: Session,
    member: WorkspaceMember,
    *,
    caller_user_id: str,
) -> dict[str, object]:
    user = session.get(UserAccount, member.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User not found: {member.user_id}")
    return {
        "user_id": member.user_id,
        "email": user.email,
        "name": user.name,
        "role": member.role,
        "status": "active",
        "joined_at": member.created_at.isoformat(),
        "invited_at": None,
        "last_active_at": None,
        "is_current_user": member.user_id == caller_user_id,
    }


def serialize_workspace_summary_for_member(
    session: Session,
    workspace: Workspace,
    *,
    user_id: str,
    role: WorkspaceRole,
    capabilities: frozenset[str],
    counts: tuple[int, int, int] | None = None,
) -> dict[str, object]:
    user = session.get(UserAccount, user_id)
    if counts is None:
        member_count = int(
            session.scalar(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace.id
                )
            )
            or 0
        )
        workflow_count: int | None = None
        database_count: int | None = None
    else:
        member_count, workflow_count, database_count = counts
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "is_default": user is not None and user.last_workspace_id == workspace.id,
        "role": role.value,
        "capabilities": sorted(capabilities),
        "member_count": member_count,
        "workflow_count": workflow_count,
        "database_count": database_count,
        "provider_count": None,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }


def serialize_workspace_membership(
    session: Session,
    member: WorkspaceMember,
    workspace: Workspace,
    *,
    current_workspace_id: str,
    counts: tuple[int, int, int] | None = None,
) -> dict[str, object]:
    role = WorkspaceRole(member.role)
    capabilities = CAPABILITIES[role]
    workspace_summary = serialize_workspace_summary_for_member(
        session,
        workspace,
        user_id=member.user_id,
        role=role,
        capabilities=capabilities,
        counts=counts,
    )
    workspace_summary["is_default"] = workspace.id == current_workspace_id
    return {
        "workspace": workspace_summary,
        "role": role.value,
        "capabilities": sorted(capabilities),
        "joined_at": member.created_at.isoformat(),
    }


def build_workspace_session(
    session: Session,
    user_id: str,
    current_workspace_id: str,
) -> dict[str, object]:
    membership_rows = list(
        session.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.workspace_id.asc())
        ).all()
    )
    workspace_ids = [workspace.id for _, workspace in membership_rows]
    counts_by_workspace: dict[str, tuple[int, int, int]] = {}
    if workspace_ids:
        params = {
            f"workspace_{index}": workspace_id for index, workspace_id in enumerate(workspace_ids)
        }
        placeholders = ", ".join(f":workspace_{index}" for index in range(len(workspace_ids)))
        count_rows = session.execute(
            text(
                "SELECT w.id, "
                "(SELECT COUNT(*) FROM workspace_members m WHERE m.workspace_id=w.id), "
                "(SELECT COUNT(*) FROM workflows f WHERE f.workspace_id=w.id), "
                "(SELECT COUNT(*) FROM test_sets d WHERE d.workspace_id=w.id) "
                f"FROM workspaces w WHERE w.id IN ({placeholders})"
            ),
            params,
        ).all()
        counts_by_workspace = {
            workspace_id: (int(members), int(workflows), int(databases))
            for workspace_id, members, workflows, databases in count_rows
        }
    memberships = [
        serialize_workspace_membership(
            session,
            member,
            workspace,
            current_workspace_id=current_workspace_id,
            counts=counts_by_workspace[workspace.id],
        )
        for member, workspace in membership_rows
    ]
    current_membership = next(
        (
            membership
            for (_, workspace), membership in zip(membership_rows, memberships, strict=True)
            if workspace.id == current_workspace_id
        ),
        None,
    )
    return {
        "current_workspace": (
            current_membership["workspace"] if current_membership is not None else None
        ),
        "memberships": memberships,
        "capabilities": (
            current_membership["capabilities"] if current_membership is not None else []
        ),
    }


def load_workspace(session: Session, workspace_id: str) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace_id}")
    return workspace


def load_member(session: Session, *, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )


def require_membership(session: Session, *, workspace_id: str, user_id: str) -> WorkspaceMember:
    member = load_member(session, workspace_id=workspace_id, user_id=user_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace_id}")
    return member


def require_capability(
    session: Session,
    *,
    workspace_id: str,
    user_id: str,
    capability: str,
) -> WorkspaceMember:
    member = require_membership(session, workspace_id=workspace_id, user_id=user_id)
    capabilities = CAPABILITIES[WorkspaceRole(member.role)]
    if capability not in capabilities:
        raise HTTPException(status_code=403, detail=f"{capability} required")
    return member


def begin_immediate_if_sqlite(session: Session) -> None:
    if session.bind is None:
        return
    if session.bind.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def transfer_workspace_owner_in_transaction(
    session: Session,
    *,
    workspace_id: str,
    actor_user_id: str,
    new_owner_user_id: str,
) -> Workspace:
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        begin_immediate_if_sqlite(session)
        workspace = session.scalar(select(Workspace).where(Workspace.id == workspace_id))
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace_id}")
        members = list(
            session.scalars(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
            )
        )
        member_by_user_id = {member.user_id: member for member in members}
        _apply_owner_transfer(
            session,
            workspace=workspace,
            member_by_user_id=member_by_user_id,
            actor_user_id=actor_user_id,
            new_owner_user_id=new_owner_user_id,
        )
        session.commit()
        return workspace

    with session.begin():
        workspace = session.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace_id}")
        members = list(
            session.scalars(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
                .with_for_update()
            )
        )
        member_by_user_id = {member.user_id: member for member in members}
        _apply_owner_transfer(
            session,
            workspace=workspace,
            member_by_user_id=member_by_user_id,
            actor_user_id=actor_user_id,
            new_owner_user_id=new_owner_user_id,
        )
        return workspace


def _apply_owner_transfer(
    session: Session,
    *,
    workspace: Workspace,
    member_by_user_id: dict[str, WorkspaceMember],
    actor_user_id: str,
    new_owner_user_id: str,
) -> None:
    caller_member = member_by_user_id.get(actor_user_id)
    if caller_member is None:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace.id}")
    if caller_member.role != WorkspaceRole.OWNER.value:
        raise HTTPException(status_code=403, detail="only the current Owner can transfer ownership")

    target_member = member_by_user_id.get(new_owner_user_id)
    if target_member is None:
        raise HTTPException(status_code=409, detail="new owner must already be a workspace member")
    if target_member.user_id == caller_member.user_id:
        raise HTTPException(
            status_code=409, detail="cannot transfer ownership to the current Owner"
        )
    caller_member.role = WorkspaceRole.ADMIN.value
    target_member.role = WorkspaceRole.OWNER.value
    workspace.owner_user_id = new_owner_user_id
    workspace.updated_at = utcnow_naive()
    session.add(caller_member)
    session.add(target_member)
    session.add(workspace)
    session.flush()

    owner_members = [
        member for member in member_by_user_id.values() if member.role == WorkspaceRole.OWNER.value
    ]
    if len(owner_members) != 1 or workspace.owner_user_id != owner_members[0].user_id:
        raise HTTPException(status_code=409, detail="workspace owner invariant violated")
