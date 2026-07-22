from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.workspace_resolver import resolve_default_workspace


@dataclass(frozen=True, slots=True)
class ResolvedContext:
    user: AuthUser
    session: AuthSessionInfo
    workspace_id: str | None
    role: WorkspaceRole | None
    capabilities: frozenset[str]


class WorkspaceSelectorTransport(Protocol):
    @property
    def query_params(self) -> Mapping[str, str]: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


def request_workspace_selector(
    request: WorkspaceSelectorTransport, context: AuthenticatedContext
) -> str | None:
    return (
        request.query_params.get("workspace_id")
        or request.headers.get("X-Workspace-Id")
        or context.workspace_id
    )


def resolve_workspace_access(
    session: Session,
    *,
    context: AuthenticatedContext,
    selector: str | None,
    capability: str | None = None,
) -> ResolvedContext:
    workspace_id = selector or resolve_default_workspace(session, context.user.id)
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == context.user.id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace_id}")
    role = WorkspaceRole(member.role)
    capabilities = CAPABILITIES[role]
    if capability is not None and capability not in capabilities:
        raise HTTPException(status_code=403, detail=f"{capability} required")
    return ResolvedContext(
        user=context.user,
        session=context.session,
        workspace_id=workspace_id,
        role=role,
        capabilities=capabilities,
    )


def resolve_explicit_workspace_access(
    session: Session,
    *,
    context: AuthenticatedContext,
    workspace_id: str,
    capability: str | None = None,
) -> ResolvedContext:
    return resolve_workspace_access(
        session,
        context=context,
        selector=workspace_id,
        capability=capability,
    )


def resolve_public_workspace(
    *, workspace_id: str, user: AuthUser, session: AuthSessionInfo
) -> ResolvedContext:
    return ResolvedContext(
        user=user,
        session=session,
        workspace_id=workspace_id,
        role=None,
        capabilities=frozenset(),
    )


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
    if capability not in CAPABILITIES[WorkspaceRole(member.role)]:
        raise HTTPException(status_code=403, detail=f"{capability} required")
    return member


def unresolved_context(context: AuthenticatedContext) -> ResolvedContext:
    return ResolvedContext(
        user=context.user,
        session=context.session,
        workspace_id=context.workspace_id,
        role=None,
        capabilities=frozenset(),
    )


def require_resource_workspace(
    resolved: ResolvedContext,
    resource_workspace_id: str | None,
    *,
    not_found_message: str = "Resource not found.",
) -> None:
    if resolved.workspace_id != resource_workspace_id:
        raise HTTPException(status_code=404, detail=not_found_message)
