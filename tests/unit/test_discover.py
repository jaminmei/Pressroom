"""Unit tests for provider discovery service.

Tests the extracted discover logic and seed auto-discover.
Seed providers config_schema auto-discover
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.providers.auth import AuthResult, CredentialKind
from app.providers.db import init_db
from app.providers.discover import discover_provider, discover_seed_configs
from app.providers.encryption import get_fernet
from app.providers.models import (
    ModelProviderCreate,
    ModelProviderRow,
    ProviderType,
)
from app.providers.store import ProviderStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _plain_mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep respx unit tests deterministic; transport policy has dedicated tests."""

    monkeypatch.setattr(
        "app.providers.discover.provider_ssrf_safe_client",
        lambda **kwargs: httpx.AsyncClient(
            timeout=kwargs.get("timeout", 5.0),
            follow_redirects=True,
        ),
    )


def _make_store(tmp_path: Path) -> ProviderStore:
    db_path = init_db(tmp_path / "test_discover.db")
    return ProviderStore(db_path=db_path, fernet=get_fernet(Fernet.generate_key().decode()))


def _make_row(
    provider_type: str = "engine_service",
    base_url: str = "http://localhost:8000",
    provider_id: str = "test-id",
    name: str = "Test Provider",
    config_schema: str | None = None,
) -> ModelProviderRow:
    return ModelProviderRow(
        id=provider_id,
        name=name,
        provider_type=ProviderType(provider_type),
        engine_category="ocr",
        base_url=base_url,
        api_key=None,
        auth_type="none",
        auth_config=None,
        is_enabled=1,
        is_default=0,
        response_format="doctags",
        config_schema=config_schema,
        extra_config=None,
        health_url=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


# ---------------------------------------------------------------------------
# Tests — discover_provider
# ---------------------------------------------------------------------------


class TestDiscoverProvider:
    @pytest.mark.parametrize(
        ("auth", "expected_authorization"),
        [
            (AuthResult(), None),
            (AuthResult(CredentialKind.api_key, "api-secret"), "Bearer api-secret"),
            (AuthResult(CredentialKind.bearer, "access-token"), "Bearer access-token"),
        ],
    )
    @pytest.mark.asyncio
    async def test_openai_discovery_forwards_resolved_auth(
        self,
        tmp_path: Path,
        auth: AuthResult,
        expected_authorization: str | None,
    ) -> None:
        store = _make_store(tmp_path)
        row = store.create_provider(
            ModelProviderCreate(
                name="OpenAI",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="https://provider.example/v1",
            )
        )
        requests: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"data": [{"id": "model-a"}]})

        class Resolver:
            async def resolve(self, provider: ModelProviderRow) -> AuthResult:
                _ = provider
                return auth

        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
            result = await discover_provider(
                row,
                store,
                auth_resolver=Resolver(),  # type: ignore[arg-type]
                client=client,
            )

        assert result.added == 1
        assert requests[0].headers.get("authorization") == expected_authorization

    @respx.mock
    @pytest.mark.asyncio
    async def test_engine_service_discovers_config(self, tmp_path: Path) -> None:
        """engine_service provider calls GET /config and stores config_schema."""
        store = _make_store(tmp_path)
        row = store.create_provider(
            ModelProviderCreate(
                name="OCR Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr-engine:8080",
                auth_type="none",
            )
        )

        config_resp = {
            "engine_type": "ocr",
            "version": "1.0.0",
            "engine_name": "rapidocr-onnx",
            "config_schema": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["ch", "en"], "default": "ch"},
                },
            },
        }
        respx.get("http://ocr-engine:8080/config").mock(
            return_value=httpx.Response(200, json=config_resp)
        )

        result = await discover_provider(row, store)

        assert result.added == 1
        assert result.config_schema == config_resp["config_schema"]
        assert result.engine_name == "rapidocr-onnx"

        # Verify config_schema persisted
        updated = store.get_provider(str(row.id))
        assert updated is not None
        assert '"language"' in (updated.config_schema or "")

    @respx.mock
    @pytest.mark.asyncio
    async def test_engine_service_idempotent_model(self, tmp_path: Path) -> None:
        """Second discover skips model that already exists."""
        store = _make_store(tmp_path)
        row = store.create_provider(
            ModelProviderCreate(
                name="OCR Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr-engine:8080",
                auth_type="none",
            )
        )

        config_resp = {
            "engine_type": "ocr",
            "engine_name": "rapidocr-onnx",
            "config_schema": {"type": "object", "properties": {}},
        }
        respx.get("http://ocr-engine:8080/config").mock(
            return_value=httpx.Response(200, json=config_resp)
        )

        # First discover
        r1 = await discover_provider(row, store)
        assert r1.added == 1

        # Second discover
        r2 = await discover_provider(row, store)
        assert r2.added == 0
        assert r2.skipped == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error_raises(self, tmp_path: Path) -> None:
        """Connection failure raises httpx.HTTPError."""
        store = _make_store(tmp_path)
        row = store.create_provider(
            ModelProviderCreate(
                name="Dead Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://dead-engine:8080",
                auth_type="none",
            )
        )

        respx.get("http://dead-engine:8080/config").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(httpx.ConnectError):
            await discover_provider(row, store)

    @respx.mock
    @pytest.mark.asyncio
    async def test_openai_compatible_discovers_models(self, tmp_path: Path) -> None:
        """openai_compatible provider calls GET /models."""
        store = _make_store(tmp_path)
        row = store.create_provider(
            ModelProviderCreate(
                name="Vision Provider",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vision-provider:8080",
                auth_type="none",
            )
        )

        models_resp = {
            "data": [
                {"id": "gpt-4.1-deploy"},
                {"id": "gpt-4.1-mini-deploy"},
            ]
        }
        respx.get("http://vision-provider:8080/models").mock(
            return_value=httpx.Response(200, json=models_resp)
        )

        result = await discover_provider(row, store)

        assert result.added == 2
        assert result.config_schema is None
        assert len(result.discovered) == 2


# ---------------------------------------------------------------------------
# Tests — discover_seed_configs
# ---------------------------------------------------------------------------


class TestDiscoverSeedConfigs:
    @respx.mock
    @pytest.mark.asyncio
    async def test_populates_null_config_schema(self, tmp_path: Path) -> None:
        """Seed providers with NULL config_schema get populated."""
        store = _make_store(tmp_path)

        # Create two engine_service providers without config_schema
        store.create_provider(
            ModelProviderCreate(
                name="OCR Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr-engine:8080",
                auth_type="none",
            )
        )
        store.create_provider(
            ModelProviderCreate(
                name="Text Engine",
                provider_type=ProviderType.engine_service,
                engine_category="text",
                base_url="http://text-engine:8080",
                auth_type="none",
            )
        )

        respx.get("http://ocr-engine:8080/config").mock(
            return_value=httpx.Response(
                200,
                json={
                    "engine_type": "ocr",
                    "config_schema": {
                        "type": "object",
                        "properties": {"language": {"type": "string"}},
                    },
                },
            )
        )
        respx.get("http://text-engine:8080/config").mock(
            return_value=httpx.Response(
                200,
                json={
                    "engine_type": "text",
                    "config_schema": {
                        "type": "object",
                        "properties": {"encoding": {"type": "string"}},
                    },
                },
            )
        )

        populated = await discover_seed_configs(store)
        assert populated == 2

        # Verify config_schema stored
        providers = store.list_providers(enabled_only=False)
        ocr = next(p for p in providers if p.engine_category == "ocr")
        text = next(p for p in providers if p.engine_category == "text")
        assert ocr.config_schema is not None
        assert text.config_schema is not None

    @pytest.mark.asyncio
    async def test_skips_providers_with_existing_schema(self, tmp_path: Path) -> None:
        """Providers that already have config_schema are skipped."""
        store = _make_store(tmp_path)
        store.create_provider(
            ModelProviderCreate(
                name="OCR Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr-engine:8080",
                auth_type="none",
                config_schema={"type": "object", "properties": {"language": {"type": "string"}}},
            )
        )

        populated = await discover_seed_configs(store)
        assert populated == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_failure_logged_not_raised(self, tmp_path: Path) -> None:
        """Engine connection failure is logged but doesn't raise."""
        store = _make_store(tmp_path)
        store.create_provider(
            ModelProviderCreate(
                name="Dead Engine",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://dead-engine:8080",
                auth_type="none",
            )
        )

        respx.get("http://dead-engine:8080/config").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        # Should NOT raise
        populated = await discover_seed_configs(store)
        assert populated == 0

    @pytest.mark.asyncio
    async def test_skips_openai_compatible(self, tmp_path: Path) -> None:
        """openai_compatible providers are not auto-discovered at seed."""
        store = _make_store(tmp_path)
        store.create_provider(
            ModelProviderCreate(
                name="Vision Provider",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8080",
                auth_type="none",
            )
        )

        populated = await discover_seed_configs(store)
        assert populated == 0
