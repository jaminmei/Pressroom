from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.db  # noqa: F401
from app.config import Settings
from app.db.base import Base
from app.services.auth_service import AuthService


def _build_service(tmp_path: Path) -> AuthService:
    database_path = tmp_path / "auth-service.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(auth_session_secret="unit-test-session-secret")
    return AuthService(session_factory=session_factory, settings=settings)


def test_register_hashes_password_and_creates_session(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    issued = service.register(
        email="alice@example.com",
        password="StrongerPassword123!",
        name="Alice",
    )

    assert issued.context.user.email == "alice@example.com"
    assert issued.context.session.user_id == issued.context.user.id
    assert issued.raw_session_token


def test_logout_revokes_session_and_blocks_followup_access(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    issued = service.register(
        email="alice@example.com",
        password="StrongerPassword123!",
        name="Alice",
    )

    service.logout(issued.raw_session_token)

    try:
        service.require_authenticated(issued.raw_session_token)
    except Exception as exc:  # pragma: no cover - assertion follows
        error_code = getattr(exc, "error_code", None)
        assert error_code is not None
        assert error_code.value == "AUTH_SESSION_EXPIRED"
    else:  # pragma: no cover
        raise AssertionError("expected session to be rejected after logout")
