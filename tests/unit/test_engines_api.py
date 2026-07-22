"""Unit tests for Engines API endpoints.

Uses FastAPI TestClient with the engines router directly to avoid
importing the full app (which pulls in sqlalchemy and other deps).


"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.engines import router
from tests._api_workspace_contract import (
    install_authenticated_workspace,
    remove_authenticated_workspace,
)

app = FastAPI()
app.include_router(router)

# Provide a mock ProviderStore on app.state so the DI resolves.
_mock_store = MagicMock()
_mock_store.list_visible.return_value = []
app.state.provider_store = _mock_store


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    install_authenticated_workspace(app, monkeypatch)
    try:
        yield TestClient(app)
    finally:
        remove_authenticated_workspace(app)


class TestListEngines:
    """Test GET /api/engines."""

    def test_returns_all_eight_engines(self, client: TestClient) -> None:
        resp = client.get("/engines")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["engines"]) == 8

    def test_each_engine_has_required_fields(self, client: TestClient) -> None:
        resp = client.get("/engines")
        data = resp.json()
        required = {
            "category",
            "display_name",
            "icon",
            "description",
            "default_provider_type",
            "supported_input_types",
            "response_formats",
            "allow_multiple_models",
            "provider_count",
            "enabled_summary",
        }
        for engine in data["engines"]:
            assert required.issubset(set(engine.keys())), (
                f"Engine {engine.get('category')} missing: {required - set(engine.keys())}"
            )

    def test_vlm_engine_present(self, client: TestClient) -> None:
        resp = client.get("/engines")
        data = resp.json()
        vlm = next(e for e in data["engines"] if e["category"] == "vlm")
        assert vlm["display_name"] == "VLM / LLM"
        assert vlm["default_provider_type"] == "openai_compatible"
        assert vlm["allow_multiple_models"] is True

    def test_ocr_engine_present(self, client: TestClient) -> None:
        resp = client.get("/engines")
        data = resp.json()
        ocr = next(e for e in data["engines"] if e["category"] == "ocr")
        assert ocr["default_provider_type"] == "engine_service"
        assert ocr["allow_multiple_models"] is False

    def test_all_categories_present(self, client: TestClient) -> None:
        resp = client.get("/engines")
        data = resp.json()
        categories = {e["category"] for e in data["engines"]}
        expected = {
            "vlm",
            "ocr",
            "text",
            "markitdown",
            "docling",
            "layout_detection",
            "image_enhancement",
            "image_rotation",
        }
        assert categories == expected

    def test_provider_count_zero_with_no_providers(self, client: TestClient) -> None:
        resp = client.get("/engines")
        data = resp.json()
        for engine in data["engines"]:
            assert engine["provider_count"] == 0


class TestGetEngine:
    """Test GET /api/engines/{category}."""

    def test_valid_category_ocr(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "ocr"
        assert data["display_name"] == "OCR"
        assert data["icon"] == "ocr"
        assert "image/*" in data["supported_input_types"]

    def test_valid_category_vlm(self, client: TestClient) -> None:
        resp = client.get("/engines/vlm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "vlm"
        assert data["allow_multiple_models"] is True

    def test_valid_category_text(self, client: TestClient) -> None:
        resp = client.get("/engines/text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "text"
        assert data["default_provider_type"] == "engine_service"

    def test_valid_category_markitdown(self, client: TestClient) -> None:
        resp = client.get("/engines/markitdown")
        assert resp.status_code == 200

    def test_valid_category_docling(self, client: TestClient) -> None:
        resp = client.get("/engines/docling")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "docling"
        assert data["display_name"] == "Docling"
        assert data["default_provider_type"] == "engine_service"
        assert data["allow_multiple_models"] is False
        assert "application/pdf" in data["supported_input_types"]

    def test_valid_category_layout_detection(self, client: TestClient) -> None:
        resp = client.get("/engines/layout_detection")
        assert resp.status_code == 200

    def test_valid_category_image_enhancement(self, client: TestClient) -> None:
        resp = client.get("/engines/image_enhancement")
        assert resp.status_code == 200

    def test_valid_category_image_rotation(self, client: TestClient) -> None:
        resp = client.get("/engines/image_rotation")
        assert resp.status_code == 200

    def test_unknown_category_returns_404(self, client: TestClient) -> None:
        resp = client.get("/engines/foo")
        assert resp.status_code == 404
        assert "Unknown engine category" in resp.json()["detail"]

    def test_response_formats_not_empty(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr")
        data = resp.json()
        assert len(data["response_formats"]) > 0

    def test_supported_input_types_not_empty(self, client: TestClient) -> None:
        resp = client.get("/engines/vlm")
        data = resp.json()
        assert len(data["supported_input_types"]) > 0

    def test_includes_provider_list(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr")
        data = resp.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)

    def test_includes_provider_count(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr")
        data = resp.json()
        assert "provider_count" in data
        assert data["provider_count"] == 0

    def test_includes_enabled_summary(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr")
        data = resp.json()
        assert "enabled_summary" in data
        assert "enabled" in data["enabled_summary"]
        assert "total" in data["enabled_summary"]


class TestEngineHealth:
    """Test GET /api/engines/{category}/health."""

    def test_unknown_category_returns_404(self, client: TestClient) -> None:
        resp = client.get("/engines/foo/health")
        assert resp.status_code == 404

    def test_valid_category_returns_summary(self, client: TestClient) -> None:
        resp = client.get("/engines/ocr/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "ocr"
        assert "providers" in data
        assert "healthy_count" in data
        assert "total_count" in data
        assert data["total_count"] == 0
