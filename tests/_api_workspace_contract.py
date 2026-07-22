from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.api.auth import get_authenticated_context
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole

TEST_USER_ID = "usr_unit_api"
TEST_WORKSPACE_ID = "ws_unit_api"


class _MembershipSession:
    """Small session double that exercises the real workspace policy dependency."""

    def __init__(self, role: WorkspaceRole) -> None:
        self._role = role

    def __enter__(self) -> _MembershipSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(role=self._role.value)


def install_authenticated_workspace(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace_id: str = TEST_WORKSPACE_ID,
) -> None:
    """Authenticate a unit-test app while retaining capability enforcement."""

    user = AuthUser(id=TEST_USER_ID, email="unit-api@example.com", name="Unit API")
    context = AuthenticatedContext(
        user=user,
        session=AuthSessionInfo(
            id="as_unit_api",
            user_id=user.id,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id=workspace_id,
        role=role,
        capabilities=CAPABILITIES[role],
    )
    app.dependency_overrides[get_authenticated_context] = lambda: context

    # ``require_workspace_capability`` still executes normally. Only its DB
    # membership lookup is replaced with a deterministic member record.
    monkeypatch.setattr(
        "app.api.auth.SessionLocal",
        lambda: _MembershipSession(role),
    )


def remove_authenticated_workspace(app: FastAPI) -> None:
    app.dependency_overrides.pop(get_authenticated_context, None)
