from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.services.workspace_permissions import WorkspaceRole


class AuthUser(BaseModel):
    id: str
    email: str
    name: str | None = None
    created_at: datetime | None = None


class AuthSessionInfo(BaseModel):
    id: str
    user_id: str
    expires_at: datetime


class AuthenticatedContext(BaseModel):
    user: AuthUser
    session: AuthSessionInfo
    workspace_id: str | None = None
    role: WorkspaceRole | None = None
    capabilities: frozenset[str] = frozenset()
    auth_kind: Literal["session", "agent_session_token"] = "session"
