"""Tests for node connection behavior.

Covers:
  Group 1: Node Registry contract (engine/model, layout_detection, engine/ocr, etc.)
  Group 2: Workflow Validator type compatibility (TYPE_INCOMPATIBLE checks)
  Group 3: No category rule violation for cross-category connections
"""

from __future__ import annotations

import pytest

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import ValidationResult, WorkflowValidator


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


@pytest.fixture()
def validator(registry: NodeRegistryService) -> WorkflowValidator:
    return WorkflowValidator(registry)


def _has_type_incompatible_error(result: ValidationResult, source_id: str, target_id: str) -> bool:
    """Check whether the validation result contains a TYPE_INCOMPATIBLE error
    for the given source→target pair."""
    return any(
        e.code == "TYPE_INCOMPATIBLE"
        and e.details.get("source") == source_id
        and e.details.get("target") == target_id
        for e in result.errors
    )


def _validate_single_connection(
    validator: WorkflowValidator,
    source_type: str,
    target_type: str,
    *,
    source_id: str = "src",
    target_id: str = "tgt",
) -> ValidationResult:
    """Build a minimal workflow with one src→tgt connection and validate it.

    The workflow includes the minimum structural nodes (input, output, end)
    so we can isolate type-compatibility assertions on the src→tgt edge.
    """
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id=source_id, type=source_type, config={}),
            WorkflowNode(id=target_id, type=target_type, config={}),
            WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
            WorkflowNode(id="out", type="end/final", config={}),
            WorkflowNode(id="end", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="inp", target=source_id),
            WorkflowConnection(source=source_id, target=target_id),
            WorkflowConnection(source="out", target="end"),
        ],
    )
    return validator.validate(definition)


# ---------------------------------------------------------------------------
# Group 1: Node Registry Contract Tests
# ---------------------------------------------------------------------------


class TestNodeRegistryContract:
    def test_engine_model_exists_with_correct_types(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/model")
        assert node_def is not None
        # Validate per-port definitions
        assert len(node_def.input_ports) == 2
        image_port = next(p for p in node_def.input_ports if p.name == "image")
        assert image_port.accepted_types == [
            "image/*",
            "image/cropped_blocks",
            "application/x-layout-result",
        ]
        text_port = next(p for p in node_def.input_ports if p.name == "text")
        assert text_port.accepted_types == ["text/raw", "text/plain"]
        assert node_def.output_types == ["text/raw"]
        assert node_def.max_inputs == -1

    def test_engine_model_has_vision_metadata(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/model")
        assert node_def is not None
        enum_metadata = node_def.config_schema["properties"]["model"]["enum_metadata"]
        assert len(enum_metadata) == 9
        for model_key, meta in enum_metadata.items():
            assert meta.get("has_vision") is True, f"Model {model_key} missing has_vision: True"

    def test_engine_vlm_no_longer_exists(self, registry: NodeRegistryService) -> None:
        assert registry.get_node_definition("engine/vlm") is None

    def test_layout_detection_outputs_layout_result_type(
        self, registry: NodeRegistryService
    ) -> None:
        node_def = registry.get_node_definition("processor/layout_detection")
        assert node_def is not None
        assert node_def.output_types == ["application/x-layout-result"]

    def test_engine_ocr_accepts_layout_result(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/ocr")
        assert node_def is not None
        # Check via input_ports
        images_port = next(p for p in node_def.input_ports if p.name == "images")
        assert "application/x-layout-result" in images_port.accepted_types
        assert node_def.max_inputs == -1

    def test_end_final_accepts_text_raw_and_plain(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("end/final")
        assert node_def is not None
        input_port = next((p for p in node_def.input_ports if p.name == "input"), None)
        assert input_port is not None
        assert "text/raw" in input_port.accepted_types
        assert "text/plain" in input_port.accepted_types

    def test_end_final_has_no_output_types(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("end/final")
        assert node_def is not None
        assert node_def.output_types == []

    def test_end_final_accepts_text_and_image(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("end/final")
        assert node_def is not None
        input_port = next((p for p in node_def.input_ports if p.name == "input"), None)
        assert input_port is not None
        assert input_port.accepted_types == [
            "text/raw",
            "text/plain",
            "text/markdown",
            "image/*",
        ]

    def test_connection_rules_empty(self, registry: NodeRegistryService) -> None:
        reg = registry.get_registry()
        assert reg.connection_rules == []


# ---------------------------------------------------------------------------
# Group 2: Workflow Validator Type Compatibility Tests
# ---------------------------------------------------------------------------


class TestTypeCompatibility:
    def test_engine_ocr_to_engine_model_valid(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "engine/ocr", "engine/model")
        assert not _has_type_incompatible_error(result, "src", "tgt")

    def test_engine_model_to_engine_model_valid(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(
            validator,
            "engine/model",
            "engine/model",
            source_id="model_a",
            target_id="model_b",
        )
        assert not _has_type_incompatible_error(result, "model_a", "model_b")

    def test_end_to_engine_blocked(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "end/final", "engine/ocr")
        assert _has_type_incompatible_error(result, "src", "tgt")

    def test_input_text_to_layout_detection_blocked(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "input/text", "processor/layout_detection")
        assert _has_type_incompatible_error(result, "src", "tgt")

    def test_engine_text_to_layout_detection_blocked(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "engine/text", "processor/layout_detection")
        assert _has_type_incompatible_error(result, "src", "tgt")

    def test_output_markdown_to_engine_ocr_blocked(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "end/final", "engine/ocr")
        assert _has_type_incompatible_error(result, "src", "tgt")

    def test_input_text_to_output_plaintext_valid(self, validator: WorkflowValidator) -> None:
        result = _validate_single_connection(validator, "input/text", "end/final")
        assert not _has_type_incompatible_error(result, "src", "tgt")


# ---------------------------------------------------------------------------
# Group 3: No Category Rule Violation
# ---------------------------------------------------------------------------


class TestNoCategoryRuleViolation:
    def test_no_category_rule_violation_for_cross_category_connections(
        self, validator: WorkflowValidator
    ) -> None:
        """engine→engine connections were previously blocked by category rules.
        After the redesign, no CONNECTION_RULE_VIOLATION should appear."""
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="model", type="engine/model", config={}),
                WorkflowNode(id="out", type="end/final", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="ocr"),
                WorkflowConnection(source="ocr", target="model"),
                WorkflowConnection(source="model", target="out"),
                WorkflowConnection(source="out", target="end"),
            ],
        )
        result = validator.validate(definition)
        rule_violations = [e for e in result.errors if e.code == "CONNECTION_RULE_VIOLATION"]
        assert rule_violations == [], (
            f"Unexpected CONNECTION_RULE_VIOLATION errors: {rule_violations}"
        )
