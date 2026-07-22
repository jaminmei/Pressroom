from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models.db  # noqa: F401
from app.config import Settings
from app.db.base import Base
from app.models.db.auth_session import AuthSession
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.auth_service import AuthService
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole


def _build_service(tmp_path: Path, *, enforced: bool) -> AuthService:
    database_path = tmp_path / "auth-service-workspace.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(
        auth_session_secret="unit-test-session-secret",
        workspace_rbac_enforced=enforced,
    )
    return AuthService(session_factory=session_factory, settings=settings)


def _create_user(
    session: Session,
    *,
    user_id: str,
    email: str,
    created_at: datetime,
) -> UserAccount:
    user = UserAccount(
        id=user_id,
        email=email,
        password_hash="pbkdf2_sha256$390000$00$00",
        name=None,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    session.commit()
    return user


def _add_membership(
    session: Session,
    *,
    workspace_id: str,
    user_id: str,
    role: WorkspaceRole,
    created_at: datetime,
) -> None:
    session.add(
        Workspace(
            id=workspace_id,
            name=f"Workspace {workspace_id}",
            slug=workspace_id,
            description=None,
            owner_user_id=user_id,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.add(
        WorkspaceMember(
            id=f"wsm_{workspace_id}_{user_id}",
            workspace_id=workspace_id,
            user_id=user_id,
            role=role.value,
            created_at=created_at,
        )
    )
    session.commit()


def test_build_context_populates_owner_membership_when_enforced(tmp_path: Path) -> None:
    service = _build_service(tmp_path, enforced=True)
    now = datetime(2026, 7, 8, 9, 0, 0)

    with service._session_factory() as session:
        user = _create_user(session, user_id="usr_owner", email="owner@example.com", created_at=now)
        _add_membership(
            session,
            workspace_id="ws_owner",
            user_id="usr_owner",
            role=WorkspaceRole.OWNER,
            created_at=now,
        )
        auth_session = AuthSession(
            id="as_owner",
            user_id=user.id,
            session_token_hash="hash",
            expires_at=now,
            created_at=now,
            last_seen_at=now,
        )

        context = service._build_context(session=session, user=user, auth_session=auth_session)

    assert context.workspace_id == "ws_owner"
    assert context.role == WorkspaceRole.OWNER
    assert context.capabilities == CAPABILITIES[WorkspaceRole.OWNER]


def test_build_context_leaves_workspace_fields_empty_when_enforcement_off(tmp_path: Path) -> None:
    service = _build_service(tmp_path, enforced=False)
    now = datetime(2026, 7, 8, 9, 0, 0)

    with service._session_factory() as session:
        user = _create_user(session, user_id="usr_off", email="off@example.com", created_at=now)
        auth_session = AuthSession(
            id="as_off",
            user_id=user.id,
            session_token_hash="hash",
            expires_at=now,
            created_at=now,
            last_seen_at=now,
        )

        context = service._build_context(session=session, user=user, auth_session=auth_session)

    assert context.workspace_id is None
    assert context.role is None
    assert context.capabilities == frozenset()


def test_build_context_uses_last_membership_when_enforced_and_present(tmp_path: Path) -> None:
    service = _build_service(tmp_path, enforced=True)
    now = datetime(2026, 7, 8, 9, 0, 0)

    with service._session_factory() as session:
        user = _create_user(
            session,
            user_id="usr_last",
            email="last@example.com",
            created_at=now,
        )
        user.last_workspace_id = "ws_recent"
        session.commit()
        _add_membership(
            session,
            workspace_id="ws_old",
            user_id="usr_last",
            role=WorkspaceRole.VIEWER,
            created_at=datetime(2026, 7, 8, 8, 0, 0),
        )
        _add_membership(
            session,
            workspace_id="ws_recent",
            user_id="usr_last",
            role=WorkspaceRole.ADMIN,
            created_at=datetime(2026, 7, 8, 10, 0, 0),
        )
        auth_session = AuthSession(
            id="as_last",
            user_id=user.id,
            session_token_hash="hash",
            expires_at=now,
            created_at=now,
            last_seen_at=now,
        )

        context = service._build_context(session=session, user=user, auth_session=auth_session)

    assert context.workspace_id == "ws_recent"
    assert context.role == WorkspaceRole.ADMIN
    assert context.capabilities == CAPABILITIES[WorkspaceRole.ADMIN]


def test_build_context_auto_creates_personal_workspace_when_enforced_and_unjoined(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path, enforced=True)
    now = datetime(2026, 7, 8, 9, 0, 0)

    with service._session_factory() as session:
        user = _create_user(
            session,
            user_id="usr_personal",
            email="personal@example.com",
            created_at=now,
        )
        auth_session = AuthSession(
            id="as_personal",
            user_id=user.id,
            session_token_hash="hash",
            expires_at=now,
            created_at=now,
            last_seen_at=now,
        )

        context = service._build_context(session=session, user=user, auth_session=auth_session)

    assert context.workspace_id == "ws_personal_usr_personal"
    assert context.role == WorkspaceRole.OWNER
    assert context.capabilities == CAPABILITIES[WorkspaceRole.OWNER]
