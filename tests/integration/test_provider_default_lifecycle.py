"""Integration coverage for scoped Provider default lifecycle rules."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import get_authenticated_context
from app.api.providers import models_router
from app.api.providers import router as providers_router
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.providers.auth_registry import register_builtin_strategies
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workspace.db'}")
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(
            UserAccount(
                id="usr_provider_default",
                email="provider-default@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
                name=None,
            )
        )
        session.add(
            Workspace(
                id="ws_provider_default",
                name="Provider Defaults",
                slug=None,
                description=None,
                owner_user_id="usr_provider_default",
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_provider_default",
                workspace_id="ws_provider_default",
                user_id="usr_provider_default",
                role="owner",
            )
        )
        session.commit()

    app = FastAPI()
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.dependency_overrides[get_authenticated_context] = lambda: AuthenticatedContext(
        user=AuthUser(id="usr_provider_default", email="provider-default@example.com"),
        session=AuthSessionInfo(
            id="as_provider_default",
            user_id="usr_provider_default",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id="ws_provider_default",
    )
    app.state.provider_store = ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    register_builtin_strategies()
    return TestClient(app)


def _workspace_ocr(name: str) -> dict[str, str]:
    return {
        "name": name,
        "provider_type": "engine_service",
        "engine_category": "ocr",
        "base_url": f"http://{name.lower().replace(' ', '-')}:8002",
    }


def test_first_enabled_workspace_provider_becomes_default(client: TestClient) -> None:
    # Given an empty workspace/category
    # When the first enabled provider is created
    created = client.post("/api/providers", json=_workspace_ocr("First OCR"))

    # Then it is the workspace default
    assert created.status_code == 201
    assert created.json()["is_default"] is True
    default = client.get("/api/providers/default", params={"category": "ocr"})
    assert default.json()["id"] == created.json()["id"]


def test_deleting_default_promotes_oldest_enabled_sibling(client: TestClient) -> None:
    # Given two enabled workspace providers in one category
    first = client.post("/api/providers", json=_workspace_ocr("First OCR")).json()
    second = client.post("/api/providers", json=_workspace_ocr("Second OCR")).json()

    # When the default is deleted
    deleted = client.delete(f"/api/providers/{first['id']}")

    # Then the oldest eligible sibling becomes the sole default
    assert deleted.status_code == 204
    default = client.get("/api/providers/default", params={"category": "ocr"})
    assert default.json()["id"] == second["id"]
    assert client.get(f"/api/providers/{second['id']}").json()["is_default"] is True


def test_setting_workspace_sibling_default_clears_previous_default(client: TestClient) -> None:
    # Given two enabled workspace providers in one category
    first = client.post("/api/providers", json=_workspace_ocr("First OCR")).json()
    second = client.post("/api/providers", json=_workspace_ocr("Second OCR")).json()

    # When the second provider is explicitly selected as default
    updated = client.put(f"/api/providers/{second['id']}/default")

    # Then the category has exactly one workspace default
    assert updated.status_code == 200
    assert updated.json()["id"] == second["id"]
    providers = client.get("/api/providers", params={"category": "ocr"}).json()
    default_ids = [provider["id"] for provider in providers if provider["is_default"]]
    assert default_ids == [second["id"]]
    assert client.get(f"/api/providers/{first['id']}").json()["is_default"] is False


def test_deleting_workspace_default_falls_back_to_enabled_system_default(
    client: TestClient,
) -> None:
    # Given a system default and a workspace override
    state = client.app.state
    store: ProviderStore = state.provider_store
    system = store.create_provider(
        ModelProviderCreate(
            name="System OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://system-ocr:8002",
            scope=ProviderScope.system,
        )
    )
    workspace = client.post("/api/providers", json=_workspace_ocr("Workspace OCR")).json()

    # When the workspace override is deleted without a sibling
    deleted = client.delete(f"/api/providers/{workspace['id']}")

    # Then the system default is returned
    assert deleted.status_code == 204
    default = client.get("/api/providers/default", params={"category": "ocr"})
    assert default.json()["id"] == system.id


def test_deleting_last_workspace_default_without_system_fallback_is_rejected(
    client: TestClient,
) -> None:
    # Given the only enabled workspace provider in a category
    workspace = client.post("/api/providers", json=_workspace_ocr("Only OCR")).json()

    # When its deletion would leave no default or fallback
    deleted = client.delete(f"/api/providers/{workspace['id']}")

    # Then the lifecycle invariant is preserved
    assert deleted.status_code == 409
    assert client.get(f"/api/providers/{workspace['id']}").status_code == 200


def test_explicit_missing_provider_id_does_not_fallback_to_default(client: TestClient) -> None:
    # Given a visible default provider
    client.post("/api/providers", json=_workspace_ocr("Default OCR"))

    # When an explicit missing provider id is requested
    missing = client.get("/api/providers/missing-provider")

    # Then explicit lookup fails closed instead of falling back to default
    assert missing.status_code == 404
