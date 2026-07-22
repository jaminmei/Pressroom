from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole


class WorkspaceAutoCreateError(RuntimeError):
    pass


def resolve_default_workspace(session: Session, user_id: str) -> str:
    memberships = list(
        session.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.workspace_id.asc())
        ).scalars()
    )

    if not memberships:
        return ensure_personal_workspace(session, user_id)

    user = session.get(UserAccount, user_id)
    fallback_workspace_id = memberships[0].workspace_id
    if user is not None and user.last_workspace_id is not None:
        membership_by_workspace = {
            membership.workspace_id: membership for membership in memberships
        }
        if user.last_workspace_id in membership_by_workspace:
            return user.last_workspace_id
        user.last_workspace_id = fallback_workspace_id
        session.add(user)
        session.commit()

    return fallback_workspace_id


def ensure_personal_workspace(session: Session, user_id: str) -> str:
    user = session.get(UserAccount, user_id)
    if user is None:
        raise WorkspaceAutoCreateError(
            f"Cannot auto-create personal workspace: user '{user_id}' not found"
        )

    workspace_id = f"ws_personal_{user_id}"
    membership_id = f"wsm_personal_{user_id}"
    workspace_slug = f"personal_{user_id}"
    workspace_name = f"{user.email}'s workspace"

    existing_workspace = session.execute(
        select(Workspace).where(
            Workspace.owner_user_id == user_id,
            Workspace.slug == workspace_slug,
        )
    ).scalar_one_or_none()
    if existing_workspace is not None:
        existing_membership = session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == existing_workspace.id,
                WorkspaceMember.user_id == user_id,
            )
        ).scalar_one_or_none()
        if existing_membership is None:
            session.add(
                WorkspaceMember(
                    id=membership_id,
                    workspace_id=existing_workspace.id,
                    user_id=user_id,
                    role=WorkspaceRole.OWNER.value,
                )
            )
            _commit_workspace_autocreate(session, user_id)
        return existing_workspace.id

    session.add(
        Workspace(
            id=workspace_id,
            name=workspace_name,
            slug=workspace_slug,
            description=None,
            owner_user_id=user_id,
            created_at=_now_if_missing(user.created_at),
            updated_at=_now_if_missing(user.updated_at),
        )
    )
    session.add(
        WorkspaceMember(
            id=membership_id,
            workspace_id=workspace_id,
            user_id=user_id,
            role=WorkspaceRole.OWNER.value,
        )
    )
    _commit_workspace_autocreate(session, user_id)
    return workspace_id


def _commit_workspace_autocreate(session: Session, user_id: str) -> None:
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise WorkspaceAutoCreateError(
            f"Failed to auto-create personal workspace for user '{user_id}'"
        ) from exc


def _now_if_missing(value: datetime | None) -> datetime:
    return value or datetime.utcnow()
