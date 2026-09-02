from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator
from pydantic_core import PydanticCustomError

from app.services.workspace_permissions import WorkspaceRole

EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_WORKSPACE_NAME_LENGTH: Final = 100


def _normalize_workspace_name(value: str) -> str:
    if not isinstance(value, str):
        raise PydanticCustomError("workspace_name", "workspace name must be a string")
    normalized = value.strip()
    if not normalized:
        raise PydanticCustomError("workspace_name", "workspace name must not be empty")
    if len(normalized) > MAX_WORKSPACE_NAME_LENGTH:
        raise PydanticCustomError(
            "workspace_name",
            "workspace name must be at most {max_length} characters",
            {"max_length": MAX_WORKSPACE_NAME_LENGTH},
        )
    return normalized


class WorkspaceApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class CreateWorkspaceRequest(WorkspaceApiModel):
    name: str
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_workspace_name(value)


class UpdateWorkspaceRequest(WorkspaceApiModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_workspace_name(value)


class AddWorkspaceMemberRequest(WorkspaceApiModel):
    email: str
    role: WorkspaceRole

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise PydanticCustomError("email", "invalid email address")
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise PydanticCustomError("email", "invalid email address")
        return normalized


class ChangeWorkspaceMemberRoleRequest(WorkspaceApiModel):
    role: WorkspaceRole


class TransferWorkspaceOwnerRequest(WorkspaceApiModel):
    new_owner_user_id: str


class WorkspaceSummary(WorkspaceApiModel):
    id: str
    name: str
    description: str | None
    is_default: bool
    role: WorkspaceRole
    capabilities: list[str]
    member_count: int
    workflow_count: int | None
    database_count: int | None
    provider_count: int | None
    created_at: str
    updated_at: str


class WorkspaceMembership(WorkspaceApiModel):
    workspace: WorkspaceSummary
    role: WorkspaceRole
    capabilities: list[str]
    joined_at: str


class WorkspaceSession(WorkspaceApiModel):
    current_workspace: WorkspaceSummary | None
    memberships: list[WorkspaceMembership]
    capabilities: list[str]


class WorkspaceListResponse(WorkspaceApiModel):
    items: list[WorkspaceSummary]
    total: int


class WorkspaceMemberResponse(WorkspaceApiModel):
    user_id: str
    email: str
    name: str | None
    role: WorkspaceRole
    status: str
    joined_at: str
    invited_at: str | None
    last_active_at: str | None
    is_current_user: bool


class WorkspaceMemberListResponse(WorkspaceApiModel):
    items: list[WorkspaceMemberResponse]
    total: int


class WorkspaceAuditEventListResponse(WorkspaceApiModel):
    implemented: Literal[False] = False
    status: Literal["not_implemented"] = "not_implemented"
    items: list[dict[str, JsonValue]]
    total: int


class WorkspaceDeletionCountsResponse(WorkspaceApiModel):
    members_excluding_owner: int
    workflows: int
    databases: int
    evaluation_runs: int
    task_runs: int
    files: int
    pending_storage_cleanups: int
    workspace_providers: int


class WorkspaceDeletionImpactResponse(WorkspaceApiModel):
    can_delete: bool
    counts: WorkspaceDeletionCountsResponse


class ErrorEnvelope(WorkspaceApiModel):
    error_code: str
    message: str
    details: dict[str, JsonValue] | None = None
    trace_id: str
