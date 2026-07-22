from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

import app.models.db  # noqa: F401
from app.db.base import Base
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole
from app.services.workspace_resolver import (
    WorkspaceAutoCreateError,
    ensure_personal_workspace,
    resolve_default_workspace,
)


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "workspace-resolver.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _create_user(
    session: Session,
    *,
    user_id: str,
    email: str,
    last_workspace_id: str | None = None,
) -> UserAccount:
    user = UserAccount(
        id=user_id,
        email=email,
        password_hash="pbkdf2_sha256$390000$00$00",
        name=None,
        last_workspace_id=last_workspace_id,
    )
    session.add(user)
    session.commit()
    return user


def _add_workspace_with_membership(
    session: Session,
    *,
    workspace_id: str,
    user_id: str,
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
            role=WorkspaceRole.OWNER.value,
            created_at=created_at,
        )
    )
    session.commit()


def test_resolve_default_workspace_returns_only_membership(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_single", email="single@example.com")
        _add_workspace_with_membership(
            session,
            workspace_id="ws_only",
            user_id="usr_single",
            created_at=datetime(2026, 7, 8, 9, 0, 0),
        )

        assert resolve_default_workspace(session, "usr_single") == "ws_only"


def test_resolve_default_workspace_prefers_valid_last_workspace(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(
            session,
            user_id="usr_last",
            email="last@example.com",
            last_workspace_id="ws_recent",
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_old",
            user_id="usr_last",
            created_at=datetime(2026, 7, 8, 8, 0, 0),
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_recent",
            user_id="usr_last",
            created_at=datetime(2026, 7, 8, 10, 0, 0),
        )

        assert resolve_default_workspace(session, "usr_last") == "ws_recent"


def test_resolve_default_workspace_returns_oldest_membership_deterministically(
    tmp_path: Path,
) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_oldest", email="oldest@example.com")
        oldest_created_at = datetime(2026, 7, 8, 8, 0, 0)
        _add_workspace_with_membership(
            session,
            workspace_id="ws_b",
            user_id="usr_oldest",
            created_at=oldest_created_at,
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_a",
            user_id="usr_oldest",
            created_at=oldest_created_at,
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_c",
            user_id="usr_oldest",
            created_at=datetime(2026, 7, 8, 9, 0, 0),
        )

        assert resolve_default_workspace(session, "usr_oldest") == "ws_a"


def test_resolve_default_workspace_persists_repaired_stale_selection(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(
            session,
            user_id="usr_stale",
            email="stale@example.com",
            last_workspace_id="ws_revoked",
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_valid",
            user_id="usr_stale",
            created_at=datetime(2026, 7, 8, 8, 0, 0),
        )
        _add_workspace_with_membership(
            session,
            workspace_id="ws_other",
            user_id="usr_stale",
            created_at=datetime(2026, 7, 8, 9, 0, 0),
        )

        resolved_workspace_id = resolve_default_workspace(session, "usr_stale")

    with session_factory() as session:
        user = session.get(UserAccount, "usr_stale")
        assert user is not None
        assert resolved_workspace_id == "ws_valid"
        assert user.last_workspace_id == "ws_valid"


def test_resolve_default_workspace_creates_personal_workspace_when_user_has_no_memberships(
    tmp_path: Path,
) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_personal", email="personal@example.com")

        workspace_id = resolve_default_workspace(session, "usr_personal")

        assert workspace_id == "ws_personal_usr_personal"
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        assert workspace.name == "personal@example.com's workspace"
        assert workspace.slug == "personal_usr_personal"
        membership = session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == "usr_personal",
            )
        ).scalar_one()
        assert membership.role == WorkspaceRole.OWNER.value


def test_ensure_personal_workspace_is_idempotent(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_repeat", email="repeat@example.com")

        first_workspace_id = ensure_personal_workspace(session, "usr_repeat")
        second_workspace_id = ensure_personal_workspace(session, "usr_repeat")

        assert first_workspace_id == second_workspace_id == "ws_personal_usr_repeat"
        workspace_count = session.execute(
            select(Workspace).where(Workspace.owner_user_id == "usr_repeat")
        ).scalars()
        membership_count = session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == "usr_repeat")
        ).scalars()
        assert len(list(workspace_count)) == 1
        assert len(list(membership_count)) == 1


def test_ensure_personal_workspace_wraps_commit_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_error", email="error@example.com")

        def _raise_commit_error() -> None:
            raise SQLAlchemyError("db down")

        monkeypatch.setattr(session, "commit", _raise_commit_error)

        with pytest.raises(
            WorkspaceAutoCreateError,
            match="Failed to auto-create personal workspace for user 'usr_error'",
        ):
            ensure_personal_workspace(session, "usr_error")
