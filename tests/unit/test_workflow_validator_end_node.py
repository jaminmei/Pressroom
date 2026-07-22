from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import WorkflowValidator


def _validator() -> WorkflowValidator:
    return WorkflowValidator(node_registry=NodeRegistryService())


def _definition_without_end() -> WorkflowDefinition:
    """Workflow missing an end/final node entirely."""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
        ],
    )


def test_validate_reports_missing_end_node() -> None:
    result = _validator().validate(_definition_without_end())

    assert result.valid is False
    assert any(error.code == "WORKFLOW_NO_END" for error in result.errors)


def test_validate_reports_multiple_end_nodes() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
            WorkflowNode(id="end_2", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
            WorkflowConnection(source="output_1", target="end_2"),
        ],
    )

    result = _validator().validate(definition)

    assert result.valid is False
    assert any(error.code == "WORKFLOW_MULTIPLE_END" for error in result.errors)


def test_validate_multiple_end_nodes_does_not_emit_false_output_not_connected_error() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
            WorkflowNode(id="end_2", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_2"),
        ],
    )

    result = _validator().validate(definition)
    codes = [error.code for error in result.errors]

    assert "WORKFLOW_MULTIPLE_END" in codes
    assert "OUTPUT_NOT_CONNECTED_TO_END" not in codes


def test_validate_reports_end_node_not_terminal() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
            WorkflowNode(id="engine_2", type="engine/text", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
            WorkflowConnection(source="end_1", target="engine_2"),
        ],
    )

    result = _validator().validate(definition)

    assert result.valid is False
    assert any(error.code == "END_NODE_NOT_TERMINAL" for error in result.errors)


def test_validate_reports_disconnected_end_node_as_orphan() -> None:
    """A disconnected end/final triggers multiple-end and orphan errors."""
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
            WorkflowNode(id="end_2", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )

    result = _validator().validate(definition)

    assert result.valid is False
    assert any(error.code == "WORKFLOW_MULTIPLE_END" for error in result.errors)
    assert not any(error.code == "OUTPUT_NOT_CONNECTED_TO_END" for error in result.errors)
    assert any(warning.code == "WORKFLOW_ORPHAN_NODE" for warning in result.warnings)
