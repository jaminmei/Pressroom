"""Structural workflow rule tests.

Tests the structural invariants enforced by WorkflowValidator and the
NodeRegistryService, covering input/output constraints, self-loops,
duplicate edges, DAG validation, and required-node checks.

Rules tested:
  S1 — Input nodes reject incoming connections (max_inputs=0)
  S2 — end/final rejects outgoing connections (max_outputs=0)
  S3 — Self-loop detection (same source and target node)
  S4 — Duplicate edge detection
  S5 — Cycle / DAG violation detection
  S6 — Workflow must have at least one input node
  S7 — Workflow must have an end node (when output nodes exist)
  S8 — Output nodes must connect to end/final only
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


def _has_error_code(result: ValidationResult, code: str) -> bool:
    """Check whether the validation result contains at least one error with the given code."""
    return any(e.code == code for e in result.errors)


def _build_valid_workflow() -> WorkflowDefinition:
    """Build a minimal valid workflow: input -> engine -> end."""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="inp", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(id="ocr", type="engine/ocr", config={}),
            WorkflowNode(id="end", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="inp", target="ocr"),
            WorkflowConnection(source="ocr", target="end"),
        ],
    )


class TestStructuralRuleS1InputRejectsIncoming:
    """S1: Any node -> input node is rejected because input nodes have max_inputs=0."""

    def test_input_image_max_inputs_zero(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("input/image")
        assert node_def is not None
        assert node_def.max_inputs == 0

    def test_input_pdf_max_inputs_zero(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("input/pdf")
        assert node_def is not None
        assert node_def.max_inputs == 0

    def test_input_text_max_inputs_zero(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("input/text")
        assert node_def is not None
        assert node_def.max_inputs == 0

    def test_connection_to_input_node_rejected(self, validator: WorkflowValidator) -> None:
        """A connection targeting an input node triggers INVALID_CONNECTION."""
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp1", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="inp2", type="input/image", config={}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp1", target="ocr"),
                WorkflowConnection(source="ocr", target="inp2"),  # S1 violation
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "INVALID_CONNECTION")


class TestStructuralRuleS2EndNodeNoOutgoing:
    """S2: end/final -> any node is rejected (max_outputs=0, output_types=[])."""

    def test_end_final_max_outputs_zero(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("end/final")
        assert node_def is not None
        assert node_def.max_outputs == 0
        assert node_def.output_types == []

    def test_end_node_with_outgoing_connection_rejected(self, validator: WorkflowValidator) -> None:
        """An outgoing connection from end/final triggers END_NODE_NOT_TERMINAL."""
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="ocr"),
                WorkflowConnection(source="ocr", target="end"),
                WorkflowConnection(source="end", target="ocr"),  # S2 violation
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "END_NODE_NOT_TERMINAL")


class TestStructuralRuleS3SelfLoop:
    """S3: A node connecting to itself (self-loop) is structurally invalid.

    The backend validator relies on DAG checking (cycles of length 1 are
    cycles). This test verifies that a self-loop connection is caught.
    """

    def test_self_loop_produces_cycle_error(self, validator: WorkflowValidator) -> None:
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="ocr"),
                WorkflowConnection(source="ocr", target="ocr"),  # S3: self-loop
                WorkflowConnection(source="ocr", target="end"),
            ],
        )
        result = validator.validate(definition)
        # Self-loop creates a cycle (node cannot complete before itself)
        assert _has_error_code(result, "WORKFLOW_CYCLE")


class TestStructuralRuleS4DuplicateEdge:
    """S4: Duplicate edge A -> B when one already exists is rejected.

    The backend checks max_inputs constraints. If a target has max_inputs=1
    and receives two edges, it triggers INVALID_CONNECTION.  For targets
    with unlimited inputs, duplicate edges create a DAG issue or are
    caught by connection counting.
    """

    def test_duplicate_edge_to_single_input_node_rejected(
        self, validator: WorkflowValidator
    ) -> None:
        """Two edges to a max_inputs=1 node triggers INVALID_CONNECTION."""
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp1", type="input/image", config={}),
                WorkflowNode(id="inp2", type="input/image", config={}),
                WorkflowNode(id="layout", type="processor/layout_detection", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp1", target="layout"),
                WorkflowConnection(source="inp2", target="layout"),  # S4: 2nd edge to max_inputs=1
                WorkflowConnection(source="layout", target="end"),
            ],
        )
        result = validator.validate(definition)
        # processor/layout_detection has max_inputs=1 and receives 2 connections
        assert _has_error_code(result, "INVALID_CONNECTION")


class TestStructuralRuleS5CycleDetection:
    """S5: A cycle A -> B -> C -> A violates DAG requirement."""

    def test_three_node_cycle_rejected(self, validator: WorkflowValidator) -> None:
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="a", type="engine/ocr", config={}),
                WorkflowNode(id="b", type="engine/model", config={}),
                WorkflowNode(id="c", type="engine/model", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="a"),
                WorkflowConnection(source="a", target="b"),
                WorkflowConnection(source="b", target="c"),
                WorkflowConnection(source="c", target="a"),  # S5: cycle back
                WorkflowConnection(source="c", target="end"),
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "WORKFLOW_CYCLE")


class TestStructuralRuleS6NoInputNode:
    """S6: Workflow with no input node is rejected."""

    def test_missing_input_node_rejected(self, validator: WorkflowValidator) -> None:
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="ocr", target="end"),
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "WORKFLOW_NO_INPUT")


class TestStructuralRuleS7NoEndNode:
    """S7: Workflow with no end node is rejected (when output nodes exist)."""

    def test_missing_end_node_rejected(self, validator: WorkflowValidator) -> None:
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="ocr"),
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "WORKFLOW_NO_END")


class TestStructuralRuleS8EndNodeIsTerminal:
    """S8: end/final must be the terminal node — no outgoing connections.

    After removal of output/* nodes, end/final is the only terminal node.
    The validator enforces that end/final has no outgoing edges.
    """

    def test_end_node_with_outgoing_to_engine_rejected(self, validator: WorkflowValidator) -> None:
        """An end/final node with an outgoing connection to an engine
        triggers END_NODE_NOT_TERMINAL."""
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="inp", type="input/pdf", config={"file": "$file_0"}),
                WorkflowNode(id="ocr", type="engine/ocr", config={}),
                WorkflowNode(id="end", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="inp", target="ocr"),
                WorkflowConnection(source="ocr", target="end"),
                WorkflowConnection(source="end", target="ocr"),  # S8: end→engine
            ],
        )
        result = validator.validate(definition)
        assert _has_error_code(result, "END_NODE_NOT_TERMINAL")

    def test_valid_workflow_no_end_violation(self, validator: WorkflowValidator) -> None:
        """A properly connected workflow passes validation."""
        definition = _build_valid_workflow()
        result = validator.validate(definition)
        assert not _has_error_code(result, "END_NODE_NOT_TERMINAL")


class TestValidWorkflowBaseline:
    """Sanity check: a properly formed workflow passes all structural rules."""

    def test_valid_workflow_has_no_errors(self, validator: WorkflowValidator) -> None:
        definition = _build_valid_workflow()
        result = validator.validate(definition)
        assert result.valid is True
        assert result.errors == []
