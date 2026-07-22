from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_authenticated_context
from app.api.workspaces_support import (
    load_member,
    load_workspace,
    new_workspace_member_id,
    require_capability,
    require_membership,
    serialize_member_enriched,
    serialize_workspace_summary_for_member,
    transfer_workspace_owner_in_transaction,
    utcnow_naive,
)
from app.db.session import SessionLocal
from app.errors.error_response import canonical_error_responses
from app.models.auth import AuthenticatedContext
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace, WorkspaceDeletionImpact
from app.models.db.workspace_member import WorkspaceMember
from app.models.workspace_api import (
    AddWorkspaceMemberRequest,
    ChangeWorkspaceMemberRoleRequest,
    CreateWorkspaceRequest,
    TransferWorkspaceOwnerRequest,
    UpdateWorkspaceRequest,
    WorkspaceAuditEventListResponse,
    WorkspaceDeletionImpactResponse,
    WorkspaceListResponse,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
    WorkspaceSession,
    WorkspaceSummary,
)
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.workspace_service import WorkspaceService

router = APIRouter(
    prefix="/workspaces",
    tags=["workspaces"],
    responses=canonical_error_responses(),
)
ContextDep = Annotated[AuthenticatedContext, Depends(get_authenticated_context)]


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService()


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: CreateWorkspaceRequest, context: ContextDep) -> dict[str, object]:
    return get_workspace_service().create(context.user.id, payload)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(context: ContextDep) -> dict[str, object]:
    return get_workspace_service().list(context.user.id)


@router.get("/session", response_model=WorkspaceSession)
def get_workspace_session(request: Request, context: ContextDep) -> dict[str, object]:
    selector = request.query_params.get("workspace_id") or request.headers.get("X-Workspace-Id")
    return get_workspace_service().get_session(context.user.id, selector)


@router.post("/{workspace_id}/switch", response_model=WorkspaceSession)
def switch_workspace(workspace_id: str, context: ContextDep) -> dict[str, object]:
    return get_workspace_service().switch(context.user.id, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceSummary)
def update_workspace(
    workspace_id: str,
    payload: UpdateWorkspaceRequest,
    context: ContextDep,
) -> dict[str, object]:
    return get_workspace_service().update(context.user.id, workspace_id, payload)


@router.get("/{workspace_id}/members", response_model=WorkspaceMemberListResponse)
def list_workspace_members(workspace_id: str, context: ContextDep) -> dict[str, object]:
    with SessionLocal() as session:
        require_capability(
            session,
            workspace_id=workspace_id,
            user_id=context.user.id,
            capability="workspace.view",
        )
        load_workspace(session, workspace_id)
        members = list(
            session.scalars(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
                .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
            )
        )
        return {
            "items": [
                serialize_member_enriched(session, member, caller_user_id=context.user.id)
                for member in members
            ],
            "total": len(members),
        }


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_workspace_member(
    workspace_id: str,
    payload: AddWorkspaceMemberRequest,
    context: ContextDep,
) -> dict[str, object]:
    now = utcnow_naive()
    with SessionLocal() as session:
        require_capability(
            session,
            workspace_id=workspace_id,
            user_id=context.user.id,
            capability="workspace.manage_members",
        )
        load_workspace(session, workspace_id)
        if payload.role == WorkspaceRole.OWNER:
            raise HTTPException(
                status_code=409,
                detail="Owner role can only be assigned via transfer-owner",
            )
        target_user = session.scalar(
            select(UserAccount).where(UserAccount.email == str(payload.email))
        )
        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found for email")
        member = WorkspaceMember(
            id=new_workspace_member_id(),
            workspace_id=workspace_id,
            user_id=target_user.id,
            role=payload.role.value,
            created_at=now,
        )
        session.add(member)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="workspace member already exists") from exc
        session.refresh(member)
        return serialize_member_enriched(session, member, caller_user_id=context.user.id)


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
def change_workspace_member_role(
    workspace_id: str,
    user_id: str,
    payload: ChangeWorkspaceMemberRoleRequest,
    context: ContextDep,
) -> dict[str, object]:
    with SessionLocal() as session:
        require_capability(
            session,
            workspace_id=workspace_id,
            user_id=context.user.id,
            capability="workspace.manage_members",
        )
        load_workspace(session, workspace_id)
        if payload.role == WorkspaceRole.OWNER:
            raise HTTPException(
                status_code=409,
                detail="Owner role can only be assigned via transfer-owner",
            )
        member = load_member(session, workspace_id=workspace_id, user_id=user_id)
        if member is None:
            raise HTTPException(status_code=404, detail=f"Workspace member not found: {user_id}")
        if member.role == WorkspaceRole.OWNER.value:
            owner_count = session.scalar(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceRole.OWNER.value,
                )
            )
            if int(owner_count or 0) <= 1:
                raise HTTPException(status_code=409, detail="cannot demote last Owner")
        member.role = payload.role.value
        session.add(member)
        session.commit()
        session.refresh(member)
        return serialize_member_enriched(session, member, caller_user_id=context.user.id)


@router.get("/{workspace_id}/audit-events", response_model=WorkspaceAuditEventListResponse)
def list_workspace_audit_events(workspace_id: str, context: ContextDep) -> dict[str, object]:
    with SessionLocal() as session:
        require_capability(
            session,
            workspace_id=workspace_id,
            user_id=context.user.id,
            capability="workspace.update_settings",
        )
        load_workspace(session, workspace_id)
        # Audit persistence is not implemented; preserve the response contract.
        return {"items": [], "total": 0}


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(workspace_id: str, user_id: str, context: ContextDep) -> Response:
    with SessionLocal() as session:
        require_capability(
            session,
            workspace_id=workspace_id,
            user_id=context.user.id,
            capability="workspace.manage_members",
        )
        load_workspace(session, workspace_id)
        member = load_member(session, workspace_id=workspace_id, user_id=user_id)
        if member is None:
            raise HTTPException(status_code=404, detail=f"Workspace member not found: {user_id}")
        if member.role == WorkspaceRole.OWNER.value:
            owner_count = session.scalar(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceRole.OWNER.value,
                )
            )
            if int(owner_count or 0) <= 1:
                raise HTTPException(status_code=409, detail="cannot remove last Owner")
        session.delete(member)
        user = session.get(UserAccount, user_id)
        if user is not None and user.last_workspace_id == workspace_id:
            fallback_workspace_id = session.scalar(
                select(WorkspaceMember.workspace_id)
                .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                .where(
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.workspace_id != workspace_id,
                    Workspace.status == "active",
                )
                .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.workspace_id.asc())
            )
            user.last_workspace_id = fallback_workspace_id
            session.add(user)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workspace_id}/transfer-owner", response_model=WorkspaceSummary)
def transfer_workspace_owner(
    workspace_id: str,
    payload: TransferWorkspaceOwnerRequest,
    context: ContextDep,
) -> dict[str, object]:
    with SessionLocal() as session:
        require_membership(session, workspace_id=workspace_id, user_id=context.user.id)
        workspace = transfer_workspace_owner_in_transaction(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            new_owner_user_id=payload.new_owner_user_id,
        )
        session.refresh(workspace)
        return serialize_workspace_summary_for_member(
            session,
            workspace,
            user_id=context.user.id,
            role=WorkspaceRole.ADMIN,
            capabilities=CAPABILITIES[WorkspaceRole.ADMIN],
        )


@router.get("/{workspace_id}/deletion-impact", response_model=WorkspaceDeletionImpactResponse)
def get_workspace_deletion_impact(
    workspace_id: str,
    context: ContextDep,
) -> WorkspaceDeletionImpact:
    return get_workspace_service().deletion_impact(context.user.id, workspace_id)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: str, context: ContextDep) -> Response:
    get_workspace_service().delete(context.user.id, workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
