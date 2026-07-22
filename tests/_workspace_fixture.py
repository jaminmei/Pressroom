from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import get_authenticated_context
from app.config import get_settings
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.user_account import UserAccount
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole


def enable_rbac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    get_settings.cache_clear()


def disable_rbac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    get_settings.cache_clear()


def make_user(session_factory: Callable[[], Session], email: str) -> str:
    user_id = f"usr_{uuid4()}"
    with session_factory() as session:
        session.add(
            UserAccount(
                id=user_id,
                email=email,
                password_hash="pbkdf2_sha256$390000$00$00",
                name=None,
            )
        )
        session.commit()
    return user_id


def make_workspace_with_member(
    session_factory: Callable[[], Session],
    *,
    owner_user_id: str,
    member_role: WorkspaceRole = WorkspaceRole.OWNER,
) -> str:
    try:
        from app.models.db.workspace import Workspace
        from app.models.db.workspace_member import WorkspaceMember
    except ImportError as exc:
        raise RuntimeError(
            "Workspace and WorkspaceMember models are required for this fixture"
        ) from exc

    workspace_id = f"ws_{uuid4()}"
    with session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Test Workspace",
                slug=None,
                description=None,
                owner_user_id=owner_user_id,
            )
        )
        session.add(
            WorkspaceMember(
                id=f"wsm_{uuid4()}",
                workspace_id=workspace_id,
                user_id=owner_user_id,
                role=member_role.value,
            )
        )
        session.commit()
    return workspace_id


def make_workspace_client(
    app: FastAPI,
    *,
    user: AuthUser,
    workspace_id: str,
    role: WorkspaceRole,
) -> TestClient:
    session = AuthSessionInfo(
        id=f"as_{uuid4()}",
        user_id=user.id,
        expires_at=datetime.now(timezone.utc),
    )
    context_fields = getattr(AuthenticatedContext, "model_fields", {})
    context_data: dict[str, object] = {"user": user, "session": session}
    if "workspace_id" in context_fields:
        context_data["workspace_id"] = workspace_id
    if "role" in context_fields:
        context_data["role"] = role.value
    if "capabilities" in context_fields:
        context_data["capabilities"] = sorted(CAPABILITIES[role])

    context = AuthenticatedContext.model_validate(context_data)
    app.dependency_overrides[get_authenticated_context] = lambda: context
    return TestClient(app)
