"""Unit tests for parameter schema and health check API endpoints.

Uses FastAPI dependency_overrides to mock ProviderStore.


"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.providers import get_provider_store, router
from app.providers.models import ModelProviderRow
from tests._api_workspace_contract import install_authenticated_workspace


def _make_provider_row(**overrides) -> ModelProviderRow:
    defaults = {
        "id": "prov-1",
        "name": "Test OCR",
        "provider_type": "engine_service",
        "engine_category": "ocr",
        "base_url": "http://localhost:9000",
        "auth_type": "none",
        "is_enabled": True,
        "is_default": True,
        "response_format": "node_output",
        "config_schema": None,
        "extra_config": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "health_url": None,
    }
    defaults.update(overrides)
    return ModelProviderRow(**defaults)


def _make_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    """Create a fresh TestClient with a fresh mock store."""
    store = MagicMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_provider_store] = lambda: store
    install_authenticated_workspace(app, monkeypatch)
    return TestClient(app), store


class TestUpdateParameterSchema:
    """Test PUT /providers/{id}/parameter-schema."""

    def test_valid_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, store = _make_client(monkeypatch)
        schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        row = _make_provider_row()
        updated_row = _make_provider_row(config_schema=json.dumps(schema))

        store.get_mutable.return_value = row
        store.update_provider.return_value = updated_row
        store.list_models.return_value = []

        resp = client.put(
            "/providers/prov-1/parameter-schema",
            json={"schema": schema},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parameter_schema"] is not None
        assert data["parameter_schema"]["type"] == "object"
        store.update_provider.assert_called_once()

    def test_missing_type_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, store = _make_client(monkeypatch)
        store.get_mutable.return_value = _make_provider_row()
        store.list_models.return_value = []

        resp = client.put(
            "/providers/prov-1/parameter-schema",
            json={"schema": {"type": "string", "properties": {"key": {}}}},
        )
        assert resp.status_code == 400
        assert "type" in resp.json()["detail"].lower()

    def test_missing_properties(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, store = _make_client(monkeypatch)
        store.get_mutable.return_value = _make_provider_row()
        store.list_models.return_value = []

        resp = client.put(
            "/providers/prov-1/parameter-schema",
            json={"schema": {"type": "object"}},
        )
        assert resp.status_code == 400
        assert "properties" in resp.json()["detail"].lower()

    def test_provider_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, store = _make_client(monkeypatch)
        store.get_mutable.return_value = None
        store.get_for_runtime.return_value = None

        resp = client.put(
            "/providers/nonexistent/parameter-schema",
            json={"schema": {"type": "object", "properties": {"key": {}}}},
        )
        assert resp.status_code == 404


class TestHealthCheckEndpoint:
    """Test POST /providers/{id}/health-check."""

    def test_provider_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, store = _make_client(monkeypatch)
        store.get_for_runtime.return_value = None
        resp = client.post("/providers/nonexistent/health-check")
        assert resp.status_code == 404

    def test_healthy_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.providers.health_checker import HealthResult

        client, store = _make_client(monkeypatch)
        row = _make_provider_row()
        store.get_for_runtime.return_value = row

        health_result = HealthResult(
            provider_id="prov-1",
            provider_name="Test OCR",
            status="healthy",
            latency_ms=42,
        )

        with patch(
            "app.providers.health_checker.check_provider_health",
            new_callable=AsyncMock,
            return_value=health_result,
        ):
            resp = client.post("/providers/prov-1/health-check")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["latency_ms"] == 42

    def test_unhealthy_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.providers.health_checker import HealthResult

        client, store = _make_client(monkeypatch)
        row = _make_provider_row()
        store.get_for_runtime.return_value = row

        health_result = HealthResult(
            provider_id="prov-1",
            provider_name="Test OCR",
            status="unhealthy",
            error="Connection refused",
        )

        with patch(
            "app.providers.health_checker.check_provider_health",
            new_callable=AsyncMock,
            return_value=health_result,
        ):
            resp = client.post("/providers/prov-1/health-check")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["error"] == "Connection refused"
