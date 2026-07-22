from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.workspaces_support import (
    build_workspace_session,
    new_workspace_id,
    new_workspace_member_id,
    require_capability,
    require_membership,
    serialize_workspace_summary_for_member,
    utcnow_naive,
)
from app.db.session import SessionLocal
from app.errors import AppError, ErrorCode
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace, WorkspaceDeletionCounts, WorkspaceDeletionImpact
from app.models.db.workspace_member import WorkspaceMember
from app.models.workspace_api import CreateWorkspaceRequest, UpdateWorkspaceRequest
from app.providers.db import get_db_path
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.workspace_resolver import resolve_default_workspace


def _provider_count(workspace_id: str) -> int:
    path = get_db_path()
    if not path.is_file():
        return 0
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_providers'"
            ).fetchone()
            is None
        ):
            return 0
        row = connection.execute(
            "SELECT COUNT(*) FROM model_providers WHERE scope='workspace' AND workspace_id=?",
            (workspace_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _provider_counts(workspace_ids: list[str]) -> dict[str, int]:
    counts = {workspace_id: 0 for workspace_id in workspace_ids}
    path = get_db_path()
    if not workspace_ids or not path.is_file():
        return counts
    placeholders = ", ".join("?" for _ in workspace_ids)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_providers'"
            ).fetchone()
            is None
        ):
            return counts
        rows = connection.execute(
            "SELECT workspace_id, COUNT(*) FROM model_providers "
            f"WHERE scope='workspace' AND workspace_id IN ({placeholders}) GROUP BY workspace_id",
            workspace_ids,
        ).fetchall()
    return {**counts, **{workspace_id: int(count) for workspace_id, count in rows}}


def _summary_counts(session: Session, workspace_ids: list[str]) -> dict[str, tuple[int, int, int]]:
    if not workspace_ids:
        return {}
    placeholders = ", ".join(f":workspace_{index}" for index in range(len(workspace_ids)))
    params = {
        f"workspace_{index}": workspace_id for index, workspace_id in enumerate(workspace_ids)
    }
    rows = session.execute(
        text(
            "SELECT w.id, "
            "(SELECT COUNT(*) FROM workspace_members m WHERE m.workspace_id=w.id), "
            "(SELECT COUNT(*) FROM workflows f WHERE f.workspace_id=w.id), "
            "(SELECT COUNT(*) FROM test_sets d WHERE d.workspace_id=w.id) "
            f"FROM workspaces w WHERE w.id IN ({placeholders})"
        ),
        params,
    ).all()
    return {
        workspace_id: (int(members), int(workflows), int(databases))
        for workspace_id, members, workflows, databases in rows
    }


def _deletion_counts(session: Session, workspace_id: str) -> WorkspaceDeletionCounts:
    def count(table: str) -> int:
        return int(
            session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=:id"),
                {"id": workspace_id},
            ).scalar_one()
        )

    members = int(
        session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role != WorkspaceRole.OWNER.value,
            )
        )
        or 0
    )
    return {
        "members_excluding_owner": members,
        "workflows": count("workflows"),
        "databases": count("test_sets"),
        "evaluation_runs": count("evaluation_runs"),
        "task_runs": count("task_runs"),
        "workspace_providers": _provider_count(workspace_id),
    }


def _not_empty(counts: WorkspaceDeletionCounts) -> AppError:
    return AppError(
        ErrorCode.WORKSPACE_NOT_EMPTY,
        "Workspace still owns resources.",
        details={"required_capability": None, "counts": counts},
    )


@contextmanager
def assert_workspace_active(workspace_id: str) -> Iterator[None]:
    with SessionLocal() as session, session.begin():
        workspace = session.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        if workspace is None:
            raise AppError(ErrorCode.WORKSPACE_NOT_FOUND, "Workspace not found.")
        if workspace.status != "active":
            raise AppError(ErrorCode.REQUEST_CONFLICT, "Workspace is not active.")
        yield


class WorkspaceService:
    def create(self, user_id: str, payload: CreateWorkspaceRequest) -> dict[str, object]:
        now = utcnow_naive()
        with SessionLocal() as session:
            with session.begin():
                workspace = Workspace(
                    id=new_workspace_id(),
                    name=payload.name,
                    slug=None,
                    description=payload.description,
                    owner_user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(workspace)
                session.add(
                    WorkspaceMember(
                        id=new_workspace_member_id(),
                        workspace_id=workspace.id,
                        user_id=user_id,
                        role=WorkspaceRole.OWNER.value,
                        created_at=now,
                    )
                )
            session.refresh(workspace)
            return serialize_workspace_summary_for_member(
                session,
                workspace,
                user_id=user_id,
                role=WorkspaceRole.OWNER,
                capabilities=CAPABILITIES[WorkspaceRole.OWNER],
            )

    def list(self, user_id: str) -> dict[str, object]:
        with SessionLocal() as session:
            rows = list(
                session.execute(
                    select(WorkspaceMember, Workspace)
                    .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                    .where(WorkspaceMember.user_id == user_id)
                    .order_by(Workspace.created_at.desc(), Workspace.id.desc())
                ).all()
            )
            workspace_ids = [workspace.id for _, workspace in rows]
            counts = _summary_counts(session, workspace_ids)
            provider_counts = _provider_counts(workspace_ids)
            return {
                "items": [
                    {
                        **serialize_workspace_summary_for_member(
                            session,
                            workspace,
                            user_id=user_id,
                            role=WorkspaceRole(member.role),
                            capabilities=CAPABILITIES[WorkspaceRole(member.role)],
                        ),
                        "member_count": counts[workspace.id][0],
                        "workflow_count": counts[workspace.id][1],
                        "database_count": counts[workspace.id][2],
                        "provider_count": provider_counts[workspace.id],
                    }
                    for member, workspace in rows
                ],
                "total": len(rows),
            }

    def get_session(self, user_id: str, selector: str | None = None) -> dict[str, object]:
        with SessionLocal() as session:
            workspace_id = selector
            if workspace_id is not None:
                member = session.scalar(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user_id,
                    )
                )
                if member is None:
                    workspace_id = None
            workspace_id = workspace_id or resolve_default_workspace(session, user_id)
            return build_workspace_session(session, user_id, workspace_id)

    def switch(self, user_id: str, workspace_id: str) -> dict[str, object]:
        with SessionLocal() as session:
            require_membership(session, workspace_id=workspace_id, user_id=user_id)
            user = session.get(UserAccount, user_id)
            if user is None:
                raise AppError(ErrorCode.INTERNAL_ERROR, "Authenticated user is missing.")
            user.last_workspace_id = workspace_id
            session.add(user)
            session.commit()
            return build_workspace_session(session, user_id, workspace_id)

    def update(
        self,
        user_id: str,
        workspace_id: str,
        payload: UpdateWorkspaceRequest,
    ) -> dict[str, object]:
        with SessionLocal() as session:
            member = require_capability(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                capability="workspace.update_settings",
            )
            workspace = session.get(Workspace, workspace_id)
            if workspace is None:
                raise AppError(ErrorCode.INTERNAL_ERROR, "Workspace membership is invalid.")
            user = session.get(UserAccount, user_id)
            if user is None:
                raise AppError(ErrorCode.INTERNAL_ERROR, "Authenticated user is missing.")
            if payload.name is not None:
                workspace.name = payload.name
            if "description" in payload.model_fields_set:
                workspace.description = payload.description
            if payload.is_default is False:
                raise AppError(
                    ErrorCode.REQUEST_CONFLICT,
                    "A workspace cannot be unset as last active; "
                    "switch to another workspace instead.",
                )
            if payload.is_default is True:
                user.last_workspace_id = workspace_id
            workspace.updated_at = utcnow_naive()
            session.add_all((workspace, user))
            session.commit()
            session.refresh(workspace)
            role = WorkspaceRole(member.role)
            return serialize_workspace_summary_for_member(
                session,
                workspace,
                user_id=user_id,
                role=role,
                capabilities=CAPABILITIES[role],
            )

    def deletion_impact(self, user_id: str, workspace_id: str) -> WorkspaceDeletionImpact:
        with SessionLocal() as session:
            require_capability(
                session, workspace_id=workspace_id, user_id=user_id, capability="workspace.delete"
            )
            counts = _deletion_counts(session, workspace_id)
            return {"can_delete": not any(counts.values()), "counts": counts}

    def delete(self, user_id: str, workspace_id: str) -> None:
        with SessionLocal() as session:
            with session.begin():
                workspace = session.scalar(
                    select(Workspace).where(Workspace.id == workspace_id).with_for_update()
                )
                if workspace is None:
                    raise AppError(ErrorCode.WORKSPACE_NOT_FOUND, "Workspace not found.")
                member = require_capability(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    capability="workspace.delete",
                )
                if member.role != WorkspaceRole.OWNER.value:
                    raise AppError(ErrorCode.WORKSPACE_FORBIDDEN, "workspace.delete required")
                counts = _deletion_counts(session, workspace_id)
                if any(counts.values()):
                    raise _not_empty(counts)
                session.execute(
                    text(
                        "UPDATE users SET last_workspace_id=(SELECT m.workspace_id "
                        "FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id "
                        "WHERE m.user_id=users.id AND m.workspace_id!=:id AND w.status='active' "
                        "ORDER BY m.created_at, m.workspace_id LIMIT 1) "
                        "WHERE last_workspace_id=:id"
                    ),
                    {"id": workspace_id},
                )
                session.execute(
                    text("DELETE FROM workspace_members WHERE workspace_id=:id"),
                    {"id": workspace_id},
                )
                session.delete(workspace)
