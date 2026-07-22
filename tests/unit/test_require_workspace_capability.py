from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.api.auth as auth_api
import app.db.session as db_session
import app.models.db  # noqa: F401
from app.api.auth import ResolvedContext, require_workspace_capability
from app.db.base import Base
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "require-workspace-capability.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _create_user(
    session: Session,
    *,
    user_id: str,
    email: str,
    last_workspace_id: str | None = None,
) -> None:
    session.add(
        UserAccount(
            id=user_id,
            email=email,
            password_hash="pbkdf2_sha256$390000$00$00",
            name=None,
            last_workspace_id=last_workspace_id,
        )
    )
    session.commit()


def _add_workspace(
    session: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    member_user_id: str | None = None,
    member_role: WorkspaceRole = WorkspaceRole.OWNER,
    created_at: datetime | None = None,
) -> None:
    timestamp = created_at or datetime(2026, 7, 8, 9, 0, 0)
    session.add(
        Workspace(
            id=workspace_id,
            name=f"Workspace {workspace_id}",
            slug=workspace_id,
            description=None,
            owner_user_id=owner_user_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    if member_user_id is not None:
        session.add(
            WorkspaceMember(
                id=f"wsm_{workspace_id}_{member_user_id}",
                workspace_id=workspace_id,
                user_id=member_user_id,
                role=member_role.value,
                created_at=timestamp,
            )
        )
    session.commit()


def _context(*, user_id: str, workspace_id: str | None = None) -> AuthenticatedContext:
    return AuthenticatedContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com", name="Tester"),
        session=AuthSessionInfo(
            id=f"as_{user_id}",
            user_id=user_id,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id=workspace_id,
    )


def _build_app(context: AuthenticatedContext) -> FastAPI:
    app = FastAPI()
    guarded_dependency = Depends(require_workspace_capability("workflow.edit_draft"))

    @app.get("/guarded")
    async def guarded(
        resolved: ResolvedContext = guarded_dependency,
    ) -> dict[str, object]:
        return {
            "workspace_id": resolved.workspace_id,
            "role": None if resolved.role is None else resolved.role.value,
            "capabilities": sorted(resolved.capabilities),
        }

    from app.api.auth import get_authenticated_context

    app.dependency_overrides[get_authenticated_context] = lambda: context
    return app


def _configure_db(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "require-workspace-capability.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    auth_api.get_settings.cache_clear()


def test_enforcement_off_resolves_default_member_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_off", email="off@example.com")
        _add_workspace(
            session,
            workspace_id="ws_off",
            owner_user_id="usr_off",
            member_user_id="usr_off",
            member_role=WorkspaceRole.VIEWER,
        )

    app = _build_app(_context(user_id="usr_off"))

    with TestClient(app) as client:
        response = client.get("/guarded")

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws_off"


def test_enforcement_off_non_member_selector_returns_404(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_member", email="member@example.com")
        _create_user(session, user_id="usr_other", email="other@example.com")
        _add_workspace(
            session,
            workspace_id="ws_private",
            owner_user_id="usr_member",
            member_user_id="usr_member",
        )

    app = _build_app(_context(user_id="usr_other"))

    with TestClient(app) as client:
        response = client.get("/guarded?workspace_id=ws_private")

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found: ws_private"


def test_enforcement_modes_resolve_the_same_selected_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_modes", email="modes@example.com")
        _add_workspace(
            session,
            workspace_id="ws_selected",
            owner_user_id="usr_modes",
            member_user_id="usr_modes",
        )

    app = _build_app(_context(user_id="usr_modes"))
    resolved_workspace_ids: list[str | None] = []
    for enforced in ("false", "true"):
        monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", enforced)
        auth_api.get_settings.cache_clear()
        with TestClient(app) as client:
            response = client.get("/guarded?workspace_id=ws_selected")

        assert response.status_code == 200
        resolved_workspace_ids.append(response.json()["workspace_id"])

    assert resolved_workspace_ids == ["ws_selected", "ws_selected"]


def test_enforcement_on_owner_with_capability_is_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_owner", email="owner@example.com")
        _add_workspace(
            session,
            workspace_id="ws_owner",
            owner_user_id="usr_owner",
            member_user_id="usr_owner",
            member_role=WorkspaceRole.OWNER,
        )

    app = _build_app(_context(user_id="usr_owner", workspace_id="ws_owner"))

    with TestClient(app) as client:
        response = client.get("/guarded")

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws_owner"
    assert response.json()["role"] == WorkspaceRole.OWNER.value
    assert "workflow.edit_draft" in response.json()["capabilities"]


def test_enforcement_on_viewer_without_capability_returns_403(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_viewer", email="viewer@example.com")
        _add_workspace(
            session,
            workspace_id="ws_viewer",
            owner_user_id="usr_viewer",
            member_user_id="usr_viewer",
            member_role=WorkspaceRole.VIEWER,
        )

    app = _build_app(_context(user_id="usr_viewer", workspace_id="ws_viewer"))

    with TestClient(app) as client:
        response = client.get("/guarded")

    assert response.status_code == 403
    assert response.json()["detail"] == "workflow.edit_draft required"


def test_enforcement_on_non_member_returns_404(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_member", email="member@example.com")
        _create_user(session, user_id="usr_other", email="other@example.com")
        _add_workspace(
            session,
            workspace_id="ws_private",
            owner_user_id="usr_member",
            member_user_id="usr_member",
            member_role=WorkspaceRole.OWNER,
        )

    app = _build_app(_context(user_id="usr_other", workspace_id="ws_private"))

    with TestClient(app) as client:
        response = client.get("/guarded")

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found: ws_private"


def test_workspace_resolution_prefers_query_param(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_query", email="query@example.com")
        _add_workspace(
            session,
            workspace_id="ws_query",
            owner_user_id="usr_query",
            member_user_id="usr_query",
            member_role=WorkspaceRole.EDITOR,
        )

    app = _build_app(_context(user_id="usr_query", workspace_id="ws_other"))

    with TestClient(app) as client:
        response = client.get("/guarded?workspace_id=ws_query")

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws_query"
    assert response.json()["role"] == WorkspaceRole.EDITOR.value


def test_workspace_resolution_prefers_header_when_query_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    session_factory = _build_session_factory(tmp_path)
    _configure_db(monkeypatch, tmp_path)

    with session_factory() as session:
        _create_user(session, user_id="usr_header", email="header@example.com")
        _add_workspace(
            session,
            workspace_id="ws_header",
            owner_user_id="usr_header",
            member_user_id="usr_header",
            member_role=WorkspaceRole.ADMIN,
        )

    app = _build_app(_context(user_id="usr_header", workspace_id="ws_other"))

    with TestClient(app) as client:
        response = client.get("/guarded", headers={"X-Workspace-Id": "ws_header"})

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws_header"
    assert response.json()["role"] == WorkspaceRole.ADMIN.value
