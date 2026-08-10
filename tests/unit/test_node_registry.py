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


class TestAdaptorIterationContracts:
    def test_adaptor_node_contract_is_locked(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("processor/adaptor")

        assert node_def is not None
        assert node_def.category == "processor"
        assert node_def.config_schema["required"] == ["code"]
        properties = node_def.config_schema["properties"]
        assert "provider_id" not in properties
        assert properties["input_mode"]["enum"] == ["all_upstream", "custom_bindings"]
        assert properties["input_bindings"]["type"] == "array"
        binding_items = properties["input_bindings"]["items"]
        assert binding_items["required"] == ["name", "selector"]
        assert binding_items["properties"]["selector"]["minItems"] == 2
        assert node_def.input_ports[0].name == "input"
        assert node_def.input_ports[0].accepted_types == ["*/*"]
        assert node_def.input_ports[0].max_connections == -1
        assert node_def.output_types == ["application/x-adaptor-output"]
        assert node_def.max_inputs == -1
        assert node_def.max_outputs == -1

    def test_iteration_node_contract_is_locked(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("processor/iteration")

        assert node_def is not None
        properties = node_def.config_schema["properties"]
        assert node_def.config_schema["required"] == [
            "engine_node_type",
            "engine_config",
            "iterate_over",
            "item_input_port",
            "mode",
            "max_concurrency",
            "error_handling",
        ]
        assert "provider_id" not in properties
        assert properties["engine_node_type"]["enum"] == [
            "engine/ocr",
            "engine/model",
            "engine/text",
            "engine/markitdown",
            "engine/docling",
            "processor/image_enhance",
            "processor/rotate",
            "processor/adaptor",
        ]
        assert properties["iterate_over"]["enum"] == ["binary", "structured.elements"]
        assert properties["mode"]["enum"] == ["sequential", "parallel"]
        assert properties["error_handling"]["enum"] == [
            "terminate",
            "continue",
            "remove_failed",
        ]
        assert properties["max_concurrency"]["minimum"] == 1
        assert properties["max_concurrency"]["maximum"] == 10
        assert node_def.input_ports[0].name == "input"
        assert node_def.input_ports[0].accepted_types == ["*/*"]
        assert node_def.input_ports[0].max_connections == 1
        assert node_def.output_types == ["application/x-iteration-output"]
        assert node_def.max_inputs == 1
        assert node_def.max_outputs == -1

    def test_end_node_accepts_adaptor_output_contract(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("end/final")

        assert node_def is not None
        assert "application/x-adaptor-output" in node_def.input_types
        assert "application/x-adaptor-output" in node_def.input_ports[0].accepted_types
