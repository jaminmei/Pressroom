from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.providers import models_router
from app.api.providers import router as providers_router
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.errors.exceptions import EngineError
from app.models.auth import AuthUser
from app.models.db.workspace import Workspace
from app.models.execution import NodeOutput
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from app.services.dag_scheduler import DAGNode
from app.services.engine_client import EngineClient, make_node_executor
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
def provider_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    enable_rbac(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'provider-rbac.sqlite3'}")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    app = FastAPI()
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    db_path = init_db(tmp_path / "providers.sqlite3")
    fernet = get_fernet(Fernet.generate_key().decode())
    app.state.provider_store = ProviderStore(db_path=db_path, fernet=fernet)
    return app


@pytest.fixture()
def provider_payload() -> dict[str, object]:
    return {
        "name": "RBAC Provider",
        "provider_type": "openai_compatible",
        "engine_category": "vlm",
        "base_url": "http://vlm-test:8003",
    }


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


def test_owner_creates_provider_when_has_provider_manage(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    client = _workspace_client(provider_app, email="owner@example.com", role=WorkspaceRole.OWNER)

    response = client.post("/api/providers", json=provider_payload)

    assert response.status_code == 201
    assert response.json()["name"] == "RBAC Provider"


def test_editor_create_provider_returns_403(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    client = _workspace_client(provider_app, email="editor@example.com", role=WorkspaceRole.EDITOR)

    response = client.post("/api/providers", json=provider_payload)

    assert response.status_code == 403
    assert response.json()["detail"] == "provider.manage required"


def test_owner_lists_provider_in_active_workspace(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    owner = _workspace_client(
        provider_app, email="owner-list@example.com", role=WorkspaceRole.OWNER
    )
    created = owner.post("/api/providers", json=provider_payload)
    assert created.status_code == 201
    response = owner.get("/api/providers")

    assert response.status_code == 200
    assert [provider["id"] for provider in response.json()] == [created.json()["id"]]


def test_cross_workspace_cannot_list_detail_or_manage_provider(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    owner = _workspace_client(
        provider_app, email="owner-global@example.com", role=WorkspaceRole.OWNER
    )
    created = owner.post("/api/providers", json=provider_payload)
    assert created.status_code == 201

    workspace_b = _workspace_client(
        provider_app, email="owner-b@example.com", role=WorkspaceRole.OWNER
    )

    listed = workspace_b.get("/api/providers")
    detailed = workspace_b.get(f"/api/providers/{created.json()['id']}")
    updated = workspace_b.put(f"/api/providers/{created.json()['id']}", json={"name": "stolen"})
    deleted = workspace_b.delete(f"/api/providers/{created.json()['id']}")

    assert listed.status_code == 200
    assert listed.json() == []
    assert detailed.status_code == 404
    assert updated.status_code == 404
    assert deleted.status_code == 404


def test_system_provider_is_visible_but_read_only(provider_app: FastAPI) -> None:
    store = provider_app.state.provider_store
    system = store.create_provider(
        ModelProviderCreate(
            name="System OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://system-ocr:8002",
            scope=ProviderScope.system,
        )
    )
    owner = _workspace_client(
        provider_app, email="system-owner@example.com", role=WorkspaceRole.OWNER
    )

    listed = owner.get("/api/providers")
    updated = owner.put(f"/api/providers/{system.id}", json={"name": "changed"})
    deleted = owner.delete(f"/api/providers/{system.id}")

    assert [provider["id"] for provider in listed.json()] == [system.id]
    assert listed.json()[0]["scope"] == "system"
    assert updated.status_code == 409
    assert updated.json()["detail"] == "System providers are read-only"
    assert deleted.status_code == 409


def test_create_rejects_deleting_workspace(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    owner = _workspace_client(
        provider_app, email="deleting-owner@example.com", role=WorkspaceRole.OWNER
    )
    workspace_id = owner.headers["X-Workspace-Id"]
    with db_session.SessionLocal() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        workspace.status = "deleting"
        session.commit()

    response = owner.post("/api/providers", json=provider_payload)

    assert response.status_code == 409
    assert provider_app.state.provider_store.list_visible(workspace_id) == []


def test_discover_requires_provider_manage(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    owner = _workspace_client(
        provider_app, email="owner-discover@example.com", role=WorkspaceRole.OWNER
    )
    created = owner.post("/api/providers", json=provider_payload)
    assert created.status_code == 201
    editor = _workspace_client(
        provider_app, email="editor-discover@example.com", role=WorkspaceRole.EDITOR
    )

    response = editor.post(f"/api/providers/{created.json()['id']}/discover")

    assert response.status_code == 403
    assert response.json()["detail"] == "provider.manage required"


def test_models_endpoint_requires_provider_view_context(
    provider_app: FastAPI,
    provider_payload: dict[str, object],
) -> None:
    owner = _workspace_client(
        provider_app, email="owner-models@example.com", role=WorkspaceRole.OWNER
    )
    created = owner.post("/api/providers", json=provider_payload)
    assert created.status_code == 201
    viewer = _workspace_client(
        provider_app, email="viewer-models@example.com", role=WorkspaceRole.VIEWER
    )

    response = viewer.get("/api/models")

    assert response.status_code == 200
    assert response.json()["models"] == []


@pytest.mark.asyncio()
async def test_explicit_foreign_provider_fails_closed(provider_app: FastAPI) -> None:
    first = _workspace_client(
        provider_app,
        email="provider-runtime-a@example.com",
        role=WorkspaceRole.OWNER,
    )
    created = first.post(
        "/api/providers",
        json={
            "name": "Private runtime",
            "provider_type": "openai_compatible",
            "engine_category": "vlm",
            "base_url": "http://private-runtime:8003",
        },
    )
    second = _workspace_client(
        provider_app,
        email="provider-runtime-b@example.com",
        role=WorkspaceRole.OWNER,
    )

    class _UnusedEngineClient(EngineClient):
        async def process(self, *_args: object, **_kwargs: object) -> NodeOutput:
            pytest.fail("explicit provider miss must not fall back to settings")

    executor = make_node_executor(
        _UnusedEngineClient(),
        provider_resolver=lambda provider_id: provider_app.state.provider_store.get_for_runtime(
            provider_id,
            second.headers["X-Workspace-Id"],
        ),
    )
    node = DAGNode(
        node_id="model_1",
        node_type="engine/model",
        config={"provider_id": created.json()["id"]},
        named_inputs={},
        dependencies=set(),
    )

    with pytest.raises(EngineError):
        await executor(node, {})
