from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.engines import router as engines_router
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.errors.handlers import register_exception_handlers
from app.models.auth import AuthUser
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture()
def engine_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    enable_rbac(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'engine-rbac.sqlite3'}")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(engines_router, prefix="/api")
    db_path = init_db(tmp_path / "providers.sqlite3")
    app.state.provider_store = ProviderStore(
        db_path=db_path,
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    return app


def _workspace_client(app: FastAPI, *, email: str, role: WorkspaceRole) -> TestClient:
    user_id = make_user(db_session.SessionLocal, email)
    workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=user_id,
        member_role=role,
    )
    client = make_workspace_client(
        app,
        user=AuthUser(id=user_id, email=email),
        workspace_id=workspace_id,
        role=role,
    )
    client.headers["X-Workspace-Id"] = workspace_id
    return client


def _create_ocr_provider(
    store: ProviderStore,
    *,
    name: str,
    scope: ProviderScope,
    workspace_id: str | None = None,
) -> str:
    return store.create_provider(
        ModelProviderCreate(
            name=name,
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url=f"http://{name.lower().replace(' ', '-')}:8002",
            scope=scope,
            workspace_id=workspace_id,
        )
    ).id


def test_unauthenticated_engine_list_is_denied(engine_app: FastAPI) -> None:
    response = TestClient(engine_app).get("/api/engines")

    assert response.status_code == 401


def test_authenticated_non_member_is_denied(engine_app: FastAPI) -> None:
    member = _workspace_client(engine_app, email="member@example.com", role=WorkspaceRole.VIEWER)
    workspace_id = member.headers["X-Workspace-Id"]
    outsider_id = make_user(db_session.SessionLocal, "outsider@example.com")
    outsider = make_workspace_client(
        engine_app,
        user=AuthUser(id=outsider_id, email="outsider@example.com"),
        workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER,
    )
    outsider.headers["X-Workspace-Id"] = workspace_id

    response = outsider.get("/api/engines/ocr")

    assert response.status_code == 404


def test_provider_view_sees_only_system_and_active_workspace_summary(
    engine_app: FastAPI,
) -> None:
    viewer = _workspace_client(engine_app, email="viewer@example.com", role=WorkspaceRole.VIEWER)
    workspace_id = viewer.headers["X-Workspace-Id"]
    store: ProviderStore = engine_app.state.provider_store
    system_id = _create_ocr_provider(store, name="System OCR", scope=ProviderScope.system)
    local_id = _create_ocr_provider(
        store,
        name="Local OCR",
        scope=ProviderScope.workspace,
        workspace_id=workspace_id,
    )
    foreign_user_id = make_user(db_session.SessionLocal, "foreign@example.com")
    foreign_workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=foreign_user_id,
    )
    _create_ocr_provider(
        store,
        name="Foreign OCR",
        scope=ProviderScope.workspace,
        workspace_id=foreign_workspace_id,
    )

    list_response = viewer.get("/api/engines")
    response = viewer.get("/api/engines/ocr")

    assert list_response.status_code == 200
    ocr_summary = next(
        engine for engine in list_response.json()["engines"] if engine["category"] == "ocr"
    )
    assert ocr_summary["provider_count"] == 2
    assert response.status_code == 200
    assert response.json()["provider_count"] == 2
    assert {provider["id"] for provider in response.json()["providers"]} == {
        system_id,
        local_id,
    }


def test_engine_health_requires_provider_manage(engine_app: FastAPI) -> None:
    editor = _workspace_client(engine_app, email="editor@example.com", role=WorkspaceRole.EDITOR)

    response = editor.get("/api/engines/ocr/health")

    assert response.status_code == 403
