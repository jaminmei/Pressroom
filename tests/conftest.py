from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytest_plugins = ("tests.integration.workspace_api_support",)

_DEFAULT_DATABASE_URL = (
    f"sqlite+pysqlite:///{Path(tempfile.gettempdir()) / 'documentconversion-pytest.sqlite3'}"
)
_DATABASE_URL_WAS_MISSING = "DATABASE_URL" not in os.environ
if _DATABASE_URL_WAS_MISSING:
    os.environ["DATABASE_URL"] = _DEFAULT_DATABASE_URL


@pytest.fixture(autouse=True)
def _isolated_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if _DATABASE_URL_WAS_MISSING and os.environ.get("DATABASE_URL") == _DEFAULT_DATABASE_URL:
        monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'pytest.sqlite3'}")


@pytest.fixture
def file_resource_database() -> None:
    """Create the durable File tables for focused API tests without a full app lifespan."""
    from app.db import session as db_session
    from app.db.base import Base

    db_session._get_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())
    yield
    db_session._get_session_factory.cache_clear()
    db_session._get_engine.cache_clear()


@pytest.fixture
def authenticated_workspace_contract(monkeypatch: pytest.MonkeyPatch):
    """Opt-in authenticated owner while retaining production capability checks."""
    from app.main import app
    from tests._api_workspace_contract import (
        install_authenticated_workspace,
        remove_authenticated_workspace,
    )

    install_authenticated_workspace(app, monkeypatch)
    yield
    remove_authenticated_workspace(app)
