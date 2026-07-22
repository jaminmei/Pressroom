"""Tests for NodeRegistryService.get_model_capability().

Covers:
  - All engine/model entries expose has_vision as bool
  - Known model returns expected metadata
  - Unknown model key returns None
  - Wrong node type returns None
"""

from __future__ import annotations

import pytest

from app.services.node_registry import NodeRegistryService


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


class TestModelCapabilityMetadata:
    def test_all_models_have_has_vision_field(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/model")
        assert node_def is not None
        enum_metadata = node_def.config_schema["properties"]["model"]["enum_metadata"]
        for model_key, meta in enum_metadata.items():
            assert "has_vision" in meta, f"Model {model_key} missing 'has_vision' field"
            assert isinstance(meta["has_vision"], bool), (
                f"Model {model_key} 'has_vision' should be bool, got {type(meta['has_vision'])}"
            )

    def test_get_model_capability_returns_metadata(self, registry: NodeRegistryService) -> None:
        result = registry.get_model_capability("engine/model", "gpt-4.1")
        assert result is not None
        assert result["has_vision"] is True
        assert result["display_name"] == "GPT-4.1"

    def test_get_model_capability_unknown_model_returns_none(
        self, registry: NodeRegistryService
    ) -> None:
        result = registry.get_model_capability("engine/model", "nonexistent-model")
        assert result is None

    def test_get_model_capability_wrong_node_type_returns_none(
        self, registry: NodeRegistryService
    ) -> None:
        result = registry.get_model_capability("engine/ocr", "gpt-4.1")
        assert result is None
