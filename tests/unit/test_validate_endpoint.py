"""Tests for POST /api/workflows/validate endpoint.

Covers:
  TestValidateEndpoint:
    - Valid image->ocr->markdown->end workflow returns static.valid=true, empty dynamic.warnings
    - engine/model with no model selected returns MODEL_NOT_SELECTED info warning
    - Text workflow (input/text->engine/text->output/markdown->end) returns clean validation
    - engine/model with text-only model + image input returns MODEL_NO_VISION warning
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests._api_workspace_contract import (
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    install_authenticated_workspace(app, monkeypatch)
    try:
        yield TestClient(app)
    finally:
        remove_authenticated_workspace(app)


def _image_ocr_workflow() -> dict[str, object]:
    """Build input/image -> engine/ocr -> output/markdown -> end/final."""
    return {
        "nodes": [
            {"id": "n1", "type": "input/image", "config": {"file": "$file_0"}},
            {"id": "n2", "type": "engine/ocr", "config": {}},
            {"id": "n3", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }


def _image_model_no_selection_workflow() -> dict[str, object]:
    """Build input/image -> engine/model (no model selected) -> output/markdown -> end/final."""
    return {
        "nodes": [
            {"id": "n1", "type": "input/image", "config": {"file": "$file_0"}},
            {"id": "n2", "type": "engine/model", "config": {}},
            {"id": "n3", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }


def _text_workflow() -> dict[str, object]:
    """Build input/text -> engine/text -> output/markdown -> end/final."""
    return {
        "nodes": [
            {"id": "n1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "n2", "type": "engine/text", "config": {}},
            {"id": "n3", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }


def _image_model_workflow(model: str) -> dict[str, object]:
    """Build input/image -> engine/model(model=<model>) -> output/markdown -> end/final."""
    return {
        "nodes": [
            {"id": "n1", "type": "input/image", "config": {"file": "$file_0"}},
            {"id": "n2", "type": "engine/model", "config": {"model": model}},
            {"id": "n3", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }


_TEXT_ONLY_CAPABILITY: dict[str, object] = {
    "has_vision": False,
    "display_name": "Text-Only Model",
}


def _patched_get_model_capability(node_type: str, model_key: str) -> dict[str, object] | None:
    """Return text-only capability for 'text-only-test-model', else None."""
    if model_key == "text-only-test-model":
        return _TEXT_ONLY_CAPABILITY
    return None


class TestValidateEndpoint:
    """Tests for the POST /api/workflows/validate endpoint."""

    def test_validate_returns_static_and_dynamic(self, client: TestClient) -> None:
        """A valid image->ocr->markdown->end workflow passes static validation
        and produces no dynamic warnings."""
        payload = _image_ocr_workflow()

        response = client.post("/api/workflows/validate", json=payload)

        assert response.status_code == 200

        body = response.json()
        assert "static" in body
        assert "dynamic" in body

        assert body["static"]["valid"] is True
        assert body["static"]["errors"] == []
        assert body["dynamic"]["warnings"] == []

    def test_validate_with_no_model_selected_returns_info(self, client: TestClient) -> None:
        """An engine/model node with no model selected emits a
        MODEL_NOT_SELECTED dynamic warning with severity 'info' when
        it receives image input."""
        payload = _image_model_no_selection_workflow()

        response = client.post("/api/workflows/validate", json=payload)

        assert response.status_code == 200

        body = response.json()
        assert body["static"]["valid"] is True

        dynamic_warnings = body["dynamic"]["warnings"]
        assert len(dynamic_warnings) >= 1

        model_not_selected = [w for w in dynamic_warnings if w["code"] == "MODEL_NOT_SELECTED"]
        assert len(model_not_selected) == 1
        assert model_not_selected[0]["severity"] == "info"
        assert model_not_selected[0]["node_id"] == "n2"

    def test_validate_returns_empty_for_text_workflow(self, client: TestClient) -> None:
        """A text workflow (input/text -> engine/text -> output/markdown -> end)
        passes static validation with no errors and produces no dynamic warnings."""
        payload = _text_workflow()

        response = client.post("/api/workflows/validate", json=payload)

        assert response.status_code == 200

        body = response.json()
        assert body["static"]["valid"] is True
        assert body["static"]["errors"] == []
        assert body["dynamic"]["warnings"] == []

    def test_validate_model_no_vision_returns_warning(self, client: TestClient) -> None:
        """An engine/model node with a text-only model receiving image input
        emits a MODEL_NO_VISION dynamic warning with severity 'warning'."""
        payload = _image_model_workflow(model="text-only-test-model")

        with patch(
            "app.services.node_registry.NodeRegistryService.get_model_capability",
            side_effect=_patched_get_model_capability,
        ):
            response = client.post("/api/workflows/validate", json=payload)

        assert response.status_code == 200

        body = response.json()
        assert body["static"]["valid"] is True

        dynamic_warnings = body["dynamic"]["warnings"]
        model_no_vision = [w for w in dynamic_warnings if w["code"] == "MODEL_NO_VISION"]
        assert len(model_no_vision) == 1

        warning = model_no_vision[0]
        assert warning["severity"] == "warning"
        assert warning["node_id"] == "n2"
        assert warning["model"] == "text-only-test-model"
        assert "edge_ids" not in warning
