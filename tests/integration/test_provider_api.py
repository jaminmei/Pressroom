"""Integration tests for Provider REST API — .

 §4

25 test cases covering CRUD, default management, test-connection, discover, models.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx
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
from app.providers.auth import AuthResult
from app.providers.auth_registry import register_builtin_strategies
from app.providers.auth_registry import registry as auth_strategy_registry
from app.providers.db import init_db
from app.providers.encryption import decrypt, get_fernet
from app.providers.store import ProviderStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with isolated SQLite DB and fresh ProviderStore per test."""

    async def _resolve_custom(*_args: object, **_kwargs: object) -> AuthResult:
        return AuthResult()

    register_builtin_strategies()
    custom_registered_here = not auth_strategy_registry.has("signed_request")
    if custom_registered_here:
        auth_strategy_registry.register("signed_request", _resolve_custom)

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
                id="usr_provider_api",
                email="provider-api@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
                name=None,
            )
        )
        session.add(
            Workspace(
                id="ws_provider_api",
                name="Provider API",
                slug=None,
                description=None,
                owner_user_id="usr_provider_api",
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_provider_api",
                workspace_id="ws_provider_api",
                user_id="usr_provider_api",
                role="owner",
            )
        )
        session.commit()
    app = FastAPI()
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.dependency_overrides[get_authenticated_context] = lambda: AuthenticatedContext(
        user=AuthUser(id="usr_provider_api", email="provider-api@example.com"),
        session=AuthSessionInfo(
            id="as_provider_api",
            user_id="usr_provider_api",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id="ws_provider_api",
    )

    db_path = init_db(tmp_path / "test_api.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    app.state.provider_store = ProviderStore(db_path=db_path, fernet=fernet)
    plain_client_factory = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
        timeout=kwargs.get("timeout", 5.0),
        follow_redirects=True,
    )
    monkeypatch.setattr(
        "app.providers.discover.provider_ssrf_safe_client",
        plain_client_factory,
    )
    monkeypatch.setattr(
        "app.providers.health_checker.provider_ssrf_safe_client",
        plain_client_factory,
    )
    try:
        yield TestClient(app)
    finally:
        if custom_registered_here:
            auth_strategy_registry.unregister("signed_request")


@pytest.fixture()
def vlm_payload() -> dict:  # type: ignore[type-arg]
    return {
        "name": "Test VLM",
        "provider_type": "openai_compatible",
        "engine_category": "vlm",
        "base_url": "http://vlm-test:8003",
    }


@pytest.fixture()
def ocr_payload() -> dict:  # type: ignore[type-arg]
    return {
        "name": "Test OCR",
        "provider_type": "engine_service",
        "engine_category": "ocr",
        "base_url": "http://ocr-test:8002",
    }


# ---------------------------------------------------------------------------
# TestProviderCRUD — 11 cases
# ---------------------------------------------------------------------------


class TestProviderCRUD:
    def test_llm_api_round_trip(self, client: TestClient) -> None:
        created = client.post(
            "/api/providers",
            json={
                "name": "Chat",
                "provider_type": "llm_api",
                "engine_category": "llm",
                "base_url": "https://api.example/v1/",
                "api_protocol": "openai_responses",
                "api_key": "secret",
                "model_id": "gpt-test",
                "model_display_name": "Test Model",
                "model_context_window": 200000,
                "model_max_tokens": 8192,
                "model_reasoning": True,
                "is_chatbot_default": True,
            },
        )
        assert created.status_code == 201
        provider_id = created.json()["id"]
        assert created.json()["base_url"] == "https://api.example/v1"
        assert created.json()["has_api_key"] is True
        assert created.json()["model_context_window"] == 200000
        assert created.json()["model_max_tokens"] == 8192
        assert created.json()["model_reasoning"] is True
        assert "api_key" not in created.json()

        updated = client.put(
            f"/api/providers/{provider_id}",
            json={"api_key": "", "model_display_name": "Updated Model"},
        )
        assert updated.status_code == 200
        detail = client.get(f"/api/providers/{provider_id}")
        assert detail.status_code == 200
        assert detail.json()["api_protocol"] == "openai_responses"
        assert detail.json()["model_display_name"] == "Updated Model"
        assert detail.json()["model_context_window"] == 200000
        assert detail.json()["model_max_tokens"] == 8192
        assert detail.json()["model_reasoning"] is True
        assert detail.json()["has_api_key"] is True

    def test_non_llm_capabilities_are_null(self, client: TestClient, ocr_payload: dict) -> None:  # type: ignore[type-arg]
        created = client.post("/api/providers", json=ocr_payload)

        assert created.status_code == 201
        assert created.json()["model_context_window"] is None
        assert created.json()["model_max_tokens"] is None
        assert created.json()["model_reasoning"] is None

    def test_non_llm_rejects_model_capabilities(
        self,
        client: TestClient,
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        response = client.post(
            "/api/providers",
            json={**ocr_payload, "model_context_window": 128000},
        )

        assert response.status_code == 422
        assert "only llm_api providers" in response.json()["detail"]

    def test_llm_api_create_without_api_key_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/providers",
            json={
                "name": "Chat",
                "provider_type": "llm_api",
                "engine_category": "llm",
                "base_url": "https://api.example/v1",
                "api_protocol": "openai_chat_completions",
                "model_id": "gpt-test",
            },
        )
        assert response.status_code == 422
        assert "api_key" in response.json()["detail"]

    def test_llm_api_create_without_model_id_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/providers",
            json={
                "name": "Chat",
                "provider_type": "llm_api",
                "engine_category": "llm",
                "base_url": "https://api.example/v1",
                "api_protocol": "openai_chat_completions",
                "api_key": "secret",
            },
        )
        assert response.status_code == 422
        assert "model_id" in response.json()["detail"]

    def test_llm_api_update_resource_url_returns_422(self, client: TestClient) -> None:
        created = client.post(
            "/api/providers",
            json={
                "name": "Chat",
                "provider_type": "llm_api",
                "engine_category": "llm",
                "base_url": "https://api.example/v1",
                "api_protocol": "openai_chat_completions",
                "api_key": "secret",
                "model_id": "gpt-test",
            },
        )
        assert created.status_code == 201

        response = client.put(
            f"/api/providers/{created.json()['id']}",
            json={"base_url": "https://api.example/v1/chat/completions"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "llm_api base_url cannot include a protocol resource path"
        )

    def test_list_providers_empty(self, client: TestClient) -> None:
        r = client.get("/api/providers")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_provider(self, client: TestClient, vlm_payload: dict) -> None:  # type: ignore[type-arg]
        r = client.post("/api/providers", json=vlm_payload)
        assert r.status_code == 201
        data = r.json()
        assert "id" in data
        assert data["api_style"] == "openai"
        assert data["api_version"] is None
        assert data["has_api_key"] is False
        assert "api_key" not in data

    def test_create_provider_with_api_key(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        payload = {**vlm_payload, "api_key": "sk-secret-key"}
        r = client.post("/api/providers", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["has_api_key"] is True
        assert "api_key" not in data

    def test_create_provider_invalid_url_scheme(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        payload = {**vlm_payload, "base_url": "file:///etc/passwd"}
        r = client.post("/api/providers", json=payload)
        assert r.status_code == 422

    def test_create_and_update_reject_unregistered_auth_type(
        self,
        client: TestClient,
        vlm_payload: dict,
    ) -> None:
        auth_type = "unregistered_auth_for_api_test"
        assert not auth_strategy_registry.has(auth_type)

        rejected_create = client.post(
            "/api/providers",
            json={**vlm_payload, "auth_type": auth_type},
        )
        assert rejected_create.status_code == 422
        assert "is not registered" in rejected_create.text

        created = client.post("/api/providers", json=vlm_payload)
        assert created.status_code == 201
        rejected_update = client.put(
            f"/api/providers/{created.json()['id']}",
            json={"auth_type": auth_type},
        )
        assert rejected_update.status_code == 422
        assert "is not registered" in rejected_update.text

    def test_create_openai_provider_requires_explicit_url(self, client: TestClient) -> None:
        r = client.post(
            "/api/providers",
            json={
                "name": "Missing URL",
                "provider_type": "openai_compatible",
                "engine_category": "vlm",
            },
        )
        assert r.status_code == 422

    def test_create_azure_provider_requires_version(
        self,
        client: TestClient,
        vlm_payload: dict,
    ) -> None:
        r = client.post(
            "/api/providers",
            json={**vlm_payload, "api_style": "azure_openai"},
        )
        assert r.status_code == 422

        created = client.post(
            "/api/providers",
            json={
                **vlm_payload,
                "api_style": "azure_openai",
                "api_version": "2025-04-01-preview",
            },
        )
        assert created.status_code == 201
        assert created.json()["api_style"] == "azure_openai"
        assert created.json()["api_version"] == "2025-04-01-preview"

    def test_engine_service_rejects_openai_protocol_fields(
        self,
        client: TestClient,
        ocr_payload: dict,
    ) -> None:
        r = client.post(
            "/api/providers",
            json={**ocr_payload, "api_style": "openai"},
        )
        assert r.status_code == 422

    def test_get_provider(self, client: TestClient, vlm_payload: dict) -> None:  # type: ignore[type-arg]
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]

        r = client.get(f"/api/providers/{provider_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == provider_id
        assert data["name"] == vlm_payload["name"]
        assert data["models"] == []
        assert "api_key" not in data

    def test_get_provider_not_found(self, client: TestClient) -> None:
        r = client.get("/api/providers/bad-id")
        assert r.status_code == 404

    def test_list_providers_by_category(
        self,
        client: TestClient,
        vlm_payload: dict,
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        client.post("/api/providers", json=vlm_payload)
        client.post("/api/providers", json=ocr_payload)

        r = client.get("/api/providers?category=vlm")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "Test VLM" in names
        assert "Test OCR" not in names

    def test_update_provider(self, client: TestClient, vlm_payload: dict) -> None:  # type: ignore[type-arg]
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]
        original_base_url = created["base_url"]

        r = client.put(f"/api/providers/{provider_id}", json={"name": "Updated VLM"})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Updated VLM"
        assert data["base_url"] == original_base_url  # unchanged

    def test_custom_auth_partial_update_preserves_omitted_secret(
        self,
        client: TestClient,
        vlm_payload: dict,
    ) -> None:
        created = client.post(
            "/api/providers",
            json={
                **vlm_payload,
                "auth_type": "signed_request",
                "auth_config": {
                    "client_id": "client-before",
                    "client_secret": "secret-before",
                },
            },
        )
        assert created.status_code == 201
        provider_id = created.json()["id"]
        assert created.json()["auth_config_public"] == {"client_id": "client-before"}

        updated = client.put(
            f"/api/providers/{provider_id}",
            json={
                "auth_type": "signed_request",
                "base_url": "https://provider.example/v1",
                "auth_config": {"client_id": "client-after"},
            },
        )

        assert updated.status_code == 200
        assert updated.json()["auth_config_public"] == {"client_id": "client-after"}
        store: ProviderStore = client.app.state.provider_store
        row = store.get_provider(provider_id)
        assert row is not None
        assert row.auth_config is not None
        stored_config = json.loads(row.auth_config)
        assert decrypt(stored_config["client_secret"], store.fernet) == "secret-before"

    def test_update_provider_not_found(self, client: TestClient) -> None:
        r = client.put("/api/providers/bad-id", json={"name": "Ghost"})
        assert r.status_code == 404

    def test_delete_provider(self, client: TestClient, vlm_payload: dict) -> None:  # type: ignore[type-arg]
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]

        r = client.delete(f"/api/providers/{provider_id}")
        assert r.status_code == 409

        r2 = client.get(f"/api/providers/{provider_id}")
        assert r2.status_code == 200

    def test_delete_provider_not_found(self, client: TestClient) -> None:
        r = client.delete("/api/providers/bad-id")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# TestDefaultManagement — 2 cases
# ---------------------------------------------------------------------------


class TestDefaultManagement:
    def test_set_default(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        # Create two VLM providers
        p1 = client.post("/api/providers", json=vlm_payload).json()
        p2 = client.post("/api/providers", json={**vlm_payload, "name": "VLM 2"}).json()

        # Set p1 as default
        r = client.put(f"/api/providers/{p1['id']}/default")
        assert r.status_code == 200
        assert r.json()["is_default"] is True

        # p2 must NOT be default
        r2 = client.get(f"/api/providers/{p2['id']}")
        assert r2.json()["is_default"] is False

    def test_set_default_not_found(self, client: TestClient) -> None:
        r = client.put("/api/providers/bad-id/default")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# TestConnectionTest — 5 cases (with respx mock)
# ---------------------------------------------------------------------------


class TestConnectionTest:
    @respx.mock
    def test_test_connection_openai_success(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]
        client.post(
            f"/api/providers/{provider_id}/models",
            json={"model_id": "model-a", "display_name": "Model A"},
        )

        respx.post("http://vlm-test:8003/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )

        r = client.post(f"/api/providers/{provider_id}/test")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["model_results"][0]["status"] == "ok"

    @respx.mock
    def test_test_connection_engine_success(
        self,
        client: TestClient,
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post(
            "/api/providers",
            json={**ocr_payload, "health_url": "http://ocr-test:8002/health"},
        ).json()
        provider_id = created["id"]

        respx.get("http://ocr-test:8002/health").mock(
            return_value=httpx.Response(200, json={"status": "healthy"})
        )

        r = client.post(f"/api/providers/{provider_id}/test")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    @respx.mock
    def test_test_connection_failure(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]
        client.post(
            f"/api/providers/{provider_id}/models",
            json={"model_id": "model-a", "display_name": "Model A"},
        )

        respx.post("http://vlm-test:8003/chat/completions").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        r = client.post(f"/api/providers/{provider_id}/test")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "unhealthy"
        assert data["model_results"][0]["error"] is not None

    def test_test_connection_not_found(self, client: TestClient) -> None:
        r = client.post("/api/providers/bad-id/test")
        assert r.status_code == 404

    @respx.mock
    def test_test_connection_uses_api_key(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        """Verify Authorization: Bearer header is sent when api_key is present."""
        payload = {**vlm_payload, "api_key": "sk-secret-123", "auth_type": "api_key"}
        created = client.post("/api/providers", json=payload).json()
        provider_id = created["id"]
        client.post(
            f"/api/providers/{provider_id}/models",
            json={"model_id": "model-a", "display_name": "Model A"},
        )

        route = respx.post("http://vlm-test:8003/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )

        r = client.post(f"/api/providers/{provider_id}/test")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
        # Verify Authorization header was sent
        assert route.called
        sent_headers = route.calls[0].request.headers
        assert "authorization" in sent_headers
        assert sent_headers["authorization"].startswith("Bearer ")


# ---------------------------------------------------------------------------
# TestDiscover — 4 cases (with respx mock)
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_azure_discovery_requires_manual_deployment(
        self,
        client: TestClient,
        vlm_payload: dict,
    ) -> None:
        created = client.post(
            "/api/providers",
            json={
                **vlm_payload,
                "api_style": "azure_openai",
                "api_version": "2025-04-01-preview",
            },
        ).json()

        response = client.post(f"/api/providers/{created['id']}/discover")
        assert response.status_code == 200
        assert response.json() == {
            "discovered": [],
            "added": 0,
            "skipped": 0,
            "config_schema": None,
            "schema_discovered": False,
            "discovery_supported": False,
            "message": "Azure OpenAI deployments must be added manually.",
        }

    @respx.mock
    def test_discover_openai_compatible(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]

        # v3 spec: openai_compatible → GET {base_url}/models (no /v1 prefix)
        respx.get("http://vlm-test:8003/models").mock(
            return_value=httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "model-a"}, {"id": "model-b"}]},
            )
        )

        r = client.post(f"/api/providers/{provider_id}/discover")
        assert r.status_code == 200
        data = r.json()
        assert data["added"] == 2
        assert data["skipped"] == 0
        assert data["config_schema"] is None  # openai_compatible has no config_schema
        assert len(data["discovered"]) == 2

        # Models must appear in GET /api/providers/{id}
        detail = client.get(f"/api/providers/{provider_id}").json()
        assert len(detail["models"]) == 2

    @respx.mock
    def test_discover_engine_service(
        self,
        client: TestClient,
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=ocr_payload).json()
        provider_id = created["id"]

        # v3 spec: engine_service → GET {base_url}/config → engine_name + config_schema
        respx.get("http://ocr-test:8002/config").mock(
            return_value=httpx.Response(
                200,
                json={
                    "engine_name": "rapidocr-onnx",
                    "config_schema": {
                        "type": "object",
                        "properties": {"language": {"type": "string", "default": "ch"}},
                    },
                },
            )
        )

        r = client.post(f"/api/providers/{provider_id}/discover")
        assert r.status_code == 200
        data = r.json()
        assert data["added"] == 1
        assert data["skipped"] == 0
        assert data["config_schema"] is not None

    @respx.mock
    def test_discover_idempotent(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=vlm_payload).json()
        provider_id = created["id"]

        respx.get("http://vlm-test:8003/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})
        )

        # First discover
        r1 = client.post(f"/api/providers/{provider_id}/discover")
        assert r1.json()["added"] == 2
        assert r1.json()["skipped"] == 0

        # Second discover — same models → skipped
        r2 = client.post(f"/api/providers/{provider_id}/discover")
        assert r2.json()["added"] == 0
        assert r2.json()["skipped"] == 2

    def test_discover_not_found(self, client: TestClient) -> None:
        r = client.post("/api/providers/bad-id/discover")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# TestModels — 3 cases
# ---------------------------------------------------------------------------


class TestModels:
    def test_list_models_empty(self, client: TestClient) -> None:
        r = client.get("/api/models")
        assert r.status_code == 200
        assert r.json() == {"models": []}

    @respx.mock
    def test_list_models_multiple_providers(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        # Create VLM provider + 2 models via discover
        vlm = client.post("/api/providers", json=vlm_payload).json()
        respx.get("http://vlm-test:8003/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})
        )
        client.post(f"/api/providers/{vlm['id']}/discover")

        # Create OCR provider + 1 model via discover
        ocr = client.post("/api/providers", json=ocr_payload).json()
        respx.get("http://ocr-test:8002/config").mock(
            return_value=httpx.Response(
                200,
                json={"engine_name": "rapidocr-onnx", "config_schema": None},
            )
        )
        client.post(f"/api/providers/{ocr['id']}/discover")

        r = client.get("/api/models")
        assert r.status_code == 200
        models = r.json()["models"]
        assert len(models) == 3
        # Each model entry must include provider_name
        for m in models:
            assert "provider_name" in m

    @respx.mock
    def test_list_models_by_category(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        # VLM provider with 1 model
        vlm = client.post("/api/providers", json=vlm_payload).json()
        respx.get("http://vlm-test:8003/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "vlm-model"}]})
        )
        client.post(f"/api/providers/{vlm['id']}/discover")

        # OCR provider with 1 model
        ocr = client.post("/api/providers", json=ocr_payload).json()
        respx.get("http://ocr-test:8002/config").mock(
            return_value=httpx.Response(
                200, json={"engine_name": "rapidocr-onnx", "config_schema": None}
            )
        )
        client.post(f"/api/providers/{ocr['id']}/discover")

        r = client.get("/api/models?category=vlm")
        assert r.status_code == 200
        models = r.json()["models"]
        assert len(models) == 1
        assert models[0]["model_id"] == "vlm-model"


# ---------------------------------------------------------------------------
# TestProviderFiltering
# ---------------------------------------------------------------------------


class TestProviderFiltering:
    """Tests for provider_type and enabled_only query params on GET /providers."""

    def test_filter_by_provider_type(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        client.post("/api/providers", json=vlm_payload)
        client.post("/api/providers", json=ocr_payload)

        r = client.get("/api/providers?provider_type=openai_compatible")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "Test VLM" in names
        assert "Test OCR" not in names

    def test_filter_by_provider_type_engine_service(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        client.post("/api/providers", json=vlm_payload)
        client.post("/api/providers", json=ocr_payload)

        r = client.get("/api/providers?provider_type=engine_service")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "Test OCR" in names
        assert "Test VLM" not in names

    def test_enabled_only_excludes_disabled(self, client: TestClient, vlm_payload: dict) -> None:  # type: ignore[type-arg]
        created = client.post("/api/providers", json=vlm_payload).json()
        # Disable the provider
        client.put(f"/api/providers/{created['id']}", json={"is_enabled": False})

        # Default: enabled_only=True
        r = client.get("/api/providers")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "Test VLM" not in names

        # Explicit: enabled_only=false
        r2 = client.get("/api/providers?enabled_only=false")
        assert r2.status_code == 200
        names2 = [p["name"] for p in r2.json()]
        assert "Test VLM" in names2

    def test_combined_filters(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        client.post("/api/providers", json=vlm_payload)
        client.post("/api/providers", json=ocr_payload)

        r = client.get("/api/providers?category=vlm&provider_type=openai_compatible")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert names == ["Test VLM"]


class TestDefaultProvider:
    """Tests for GET /providers/default endpoint."""

    def test_get_default_provider(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
        ocr_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        # VLM is default, OCR is not
        vlm = client.post("/api/providers", json={**vlm_payload, "is_default": True}).json()
        client.post("/api/providers", json=ocr_payload).json()

        r = client.get("/api/providers/default?category=vlm")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == vlm["id"]
        assert data["engine_category"] == "vlm"

    def test_get_default_provider_not_found(self, client: TestClient) -> None:
        r = client.get("/api/providers/default?category=nonexistent")
        assert r.status_code == 200
        assert r.json() is None

    def test_get_default_provider_disabled(
        self,
        client: TestClient,
        vlm_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        created = client.post("/api/providers", json=vlm_payload).json()
        client.put(f"/api/providers/{created['id']}", json={"is_enabled": False})

        r = client.get("/api/providers/default?category=vlm")
        assert r.status_code == 200
        assert r.json() is None
