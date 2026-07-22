"""Unit tests for health_checker module.

Uses mocked HTTP calls to avoid external dependencies.


"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.auth import AuthResult, CredentialKind
from app.providers.health_checker import HealthResult, check_provider_health
from app.providers.models import ApiStyle, ModelProviderRow


def _make_row(
    provider_type: str = "engine_service",
    base_url: str = "http://localhost:8000",
    health_url: str | None = None,
    provider_id: str = "test-id",
    name: str = "Test Provider",
    extra_config: str | None = None,
    api_style: ApiStyle | None = None,
    api_version: str | None = None,
) -> ModelProviderRow:
    return ModelProviderRow(
        id=provider_id,
        name=name,
        provider_type=provider_type,
        engine_category="ocr",
        base_url=base_url,
        api_style=api_style,
        api_version=api_version,
        auth_type="none",
        is_enabled=True,
        is_default=False,
        response_format="node_output",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        health_url=health_url,
        extra_config=extra_config,
    )


class TestHealthResult:
    """Test HealthResult dataclass."""

    def test_default_fields(self) -> None:
        result = HealthResult(
            provider_id="abc",
            provider_name="test",
            status="healthy",
        )
        assert result.provider_id == "abc"
        assert result.latency_ms is None
        assert result.error is None
        assert result.checked_at  # should be auto-populated

    def test_all_fields(self) -> None:
        result = HealthResult(
            provider_id="abc",
            provider_name="test",
            status="unhealthy",
            latency_ms=50,
            error="timeout",
        )
        assert result.latency_ms == 50
        assert result.error == "timeout"


class TestNoHealthUrl:
    """Test that providers without health_url return no_health_url status."""

    @pytest.mark.asyncio
    async def test_no_health_url(self) -> None:
        row = _make_row(health_url=None)
        result = await check_provider_health(row)
        assert result.status == "no_health_url"
        assert result.error is not None
        assert "No health URL" in result.error


class TestCheckProviderHealth:
    """Test unified check_provider_health with health_url."""

    @pytest.mark.asyncio
    async def test_healthy(self) -> None:
        row = _make_row(health_url="http://localhost:9999/health")
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row)
            assert result.status == "healthy"
            assert result.latency_ms is not None
            assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_connection_refused(self) -> None:
        row = _make_row(health_url="http://unreachable:9999/health")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row)
            assert result.status == "unhealthy"
            assert result.error == "Provider request failed (Exception)"

    @pytest.mark.asyncio
    async def test_uses_health_url(self) -> None:
        row = _make_row(health_url="http://custom:9090/health")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row)
            assert result.status == "healthy"
            call_args = mock_client.get.call_args
            assert "custom:9090" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_ssl_verify_false_from_extra_config(self) -> None:
        row = _make_row(
            health_url="https://custom:9090/health",
            extra_config='{"ssl_verify": false}',
        )

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("app.providers.health_checker.provider_ssrf_safe_client") as client_factory:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            client_factory.return_value = mock_client

            result = await check_provider_health(row)
            assert result.status == "healthy"
            assert client_factory.call_args.kwargs["verify"] is False

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        import httpx

        row = _make_row(health_url="http://slow:9999/health")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row, timeout=1.0)
            assert result.status == "unhealthy"
            assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_measures_latency(self) -> None:
        row = _make_row(health_url="http://fast:9999/health")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row)
            assert isinstance(result.latency_ms, int)
            assert result.latency_ms >= 0


class TestCheckOpenaiCompatible:
    """Test VLM provider health check (multi-model)."""

    @pytest.mark.asyncio
    async def test_no_models_returns_no_models(self) -> None:
        row = _make_row(provider_type="openai_compatible")
        result = await check_provider_health(row, models=[])
        assert result.status == "no_models"

    @pytest.mark.asyncio
    async def test_all_models_ok(self) -> None:
        row = _make_row(provider_type="openai_compatible")
        mock_model = MagicMock()
        mock_model.model_id = "gpt-4"
        mock_model.display_name = "GPT-4"
        mock_model.is_enabled = True

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row, api_key="test-key", models=[mock_model])
            assert result.status == "healthy"
            assert result.model_results is not None
            assert len(result.model_results) == 1
            assert result.model_results[0].status == "ok"

    @pytest.mark.parametrize(
        ("auth", "expected_header"),
        [
            (AuthResult(CredentialKind.api_key, "azure-key"), ("api-key", "azure-key")),
            (
                AuthResult(CredentialKind.bearer, "azure-token"),
                ("authorization", "Bearer azure-token"),
            ),
            (AuthResult(), ("authorization", None)),
        ],
    )
    @pytest.mark.asyncio
    async def test_azure_url_version_and_credential_kind(
        self,
        auth: AuthResult,
        expected_header: tuple[str, str | None],
    ) -> None:
        row = _make_row(
            provider_type="openai_compatible",
            base_url="https://resource.example",
            api_style=ApiStyle.azure_openai,
            api_version="2025-04-01-preview",
        )
        model = MagicMock(model_id="deployment/a", display_name="Deployment", is_enabled=True)
        response = AsyncMock(status_code=200)
        response.raise_for_status = lambda: None

        class Resolver:
            async def resolve(self, provider: ModelProviderRow) -> AuthResult:
                _ = provider
                return auth

        with patch("app.providers.health_checker.provider_ssrf_safe_client") as factory:
            client = AsyncMock()
            client.post = AsyncMock(return_value=response)
            factory.return_value = client
            result = await check_provider_health(
                row,
                models=[model],
                auth_resolver=Resolver(),
            )

        assert result.status == "healthy"
        request_url = client.post.call_args.args[0]
        assert "/openai/deployments/deployment%2Fa/chat/completions" in request_url
        assert "api-version=2025-04-01-preview" in request_url
        header_name, expected_value = expected_header
        headers = httpx.Headers(client.post.call_args.kwargs["headers"])
        assert headers.get(header_name) == expected_value

    @pytest.mark.asyncio
    async def test_openai_compatible_honors_ssl_verify_false(self) -> None:
        row = _make_row(
            provider_type="openai_compatible",
            extra_config='{"ssl_verify": false}',
        )
        mock_model = MagicMock()
        mock_model.model_id = "gpt-4"
        mock_model.display_name = "GPT-4"
        mock_model.is_enabled = True

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("app.providers.health_checker.provider_ssrf_safe_client") as client_factory:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            client_factory.return_value = mock_client

            result = await check_provider_health(row, models=[mock_model])
            assert result.status == "healthy"
            assert client_factory.call_args.kwargs["verify"] is False

    @pytest.mark.asyncio
    async def test_mixed_results(self) -> None:
        row = _make_row(provider_type="openai_compatible")
        m1 = MagicMock(model_id="gpt-4", display_name="GPT-4", is_enabled=True)
        m2 = MagicMock(model_id="gpt-5", display_name="GPT-5", is_enabled=True)

        ok_resp = AsyncMock(status_code=200)
        ok_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[ok_resp, Exception("Connection refused")])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row, models=[m1, m2])
            assert result.status == "unhealthy"
            assert result.model_results is not None
            assert len(result.model_results) == 2
            assert result.model_results[0].status == "ok"
            assert result.model_results[1].status == "failed"

    @pytest.mark.asyncio
    async def test_disabled_models_skipped(self) -> None:
        row = _make_row(provider_type="openai_compatible")
        m1 = MagicMock(model_id="gpt-4", display_name="GPT-4", is_enabled=True)
        m2 = MagicMock(model_id="gpt-5", display_name="GPT-5", is_enabled=False)

        mock_resp = AsyncMock(status_code=200)
        mock_resp.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await check_provider_health(row, models=[m1, m2])
            assert result.status == "healthy"
            assert result.model_results is not None
            assert len(result.model_results) == 1  # disabled model skipped
