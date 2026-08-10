from __future__ import annotations

import pytest

from app.models.node_registry import ConnectionRule, InputPortDef, NodeDefinition, NodeRegistry
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import WorkflowValidator


def _valid_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(
                id="input_1",
                type="input/text",
                config={"file": "$file_0"},
            ),
            WorkflowNode(
                id="engine_1",
                type="engine/text",
                config={},
            ),
            WorkflowNode(
                id="end_1",
                type="end/final",
                config={},
            ),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )


def test_validator_accepts_valid_workflow() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())

    result = validator.validate(_valid_definition())

    assert result.valid is True
    assert result.errors == []


def test_validator_rejects_cycle() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = _valid_definition()
    definition.connections.append(WorkflowConnection(source="end_1", target="input_1"))

    result = validator.validate(definition)

    assert result.valid is False
    assert any(error.code == "WORKFLOW_CYCLE" for error in result.errors)


def test_validator_rejects_unknown_node_type() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = _valid_definition()
    definition.nodes[1] = WorkflowNode(id="engine_1", type="engine/unknown", config={})

    result = validator.validate(definition)

    assert result.valid is False
    assert any(error.code == "UNKNOWN_NODE_TYPE" for error in result.errors)


def test_validator_rejects_incompatible_connection() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    assert any(error.code == "TYPE_INCOMPATIBLE" for error in result.errors)


def test_validator_requires_input_and_output_nodes() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[WorkflowNode(id="engine_1", type="engine/text", config={})],
        connections=[],
    )

    result = validator.validate(definition)

    assert result.valid is False
    assert any(error.code == "WORKFLOW_NO_INPUT" for error in result.errors)
    assert any(error.code == "WORKFLOW_NO_END" for error in result.errors)


def test_validator_marks_orphan_as_non_blocking_warning() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = _valid_definition()
    definition.nodes.append(WorkflowNode(id="orphan", type="engine/text", config={}))

    result = validator.validate(definition)

    assert result.valid is True
    assert result.errors == []
    assert any(warning.code == "WORKFLOW_ORPHAN_NODE" for warning in result.warnings)
    orphan_warning = next(w for w in result.warnings if w.code == "WORKFLOW_ORPHAN_NODE")
    assert orphan_warning.severity == "non-blocking"
    assert orphan_warning.node_id == "orphan"


def test_validator_issues_include_field_and_severity() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[WorkflowNode(id="input_1", type="input/text", config={})],
        connections=[],
    )

    result = validator.validate(definition)

    missing = next(error for error in result.errors if error.code == "MISSING_REQUIRED_CONFIG")
    assert missing.severity == "blocking"
    assert missing.node_id == "input_1"
    assert missing.field == "config.file"


class _StubNodeRegistry:
    def __init__(self) -> None:
        self._registry = NodeRegistry(
            nodes=[
                NodeDefinition(
                    node_type="input/mock",
                    display_name="Input Mock",
                    category="input",
                    description="input",
                    config_schema={"required": ["file"]},
                    input_ports=[],
                    output_types=["text/plain"],
                    max_inputs=0,
                    max_outputs=1,
                ),
                NodeDefinition(
                    node_type="output/mock",
                    display_name="Output Mock",
                    category="output",
                    description="output",
                    config_schema={},
                    input_types=["text/plain"],
                    input_ports=[
                        InputPortDef(
                            name="input",
                            accepted_types=["text/plain"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["text/plain"],
                    max_inputs=1,
                    max_outputs=1,
                ),
                NodeDefinition(
                    node_type="end/final",
                    display_name="End",
                    category="end",
                    description="end",
                    config_schema={},
                    input_types=[],
                    input_ports=[],
                    output_types=[],
                    max_inputs=99,
                    max_outputs=0,
                ),
            ],
            connection_rules=[
                ConnectionRule(from_category="input", to_categories=["engine"]),
            ],
        )
        self._by_type = {node.node_type: node for node in self._registry.nodes}

    def get_node_definition(self, node_type: str) -> NodeDefinition | None:
        return self._by_type.get(node_type)

    def get_registry(self) -> NodeRegistry:
        return self._registry


def test_validator_rejects_connection_type_incompatibility() -> None:
    """Validator should reject connections where output types don't match input types."""
    validator = WorkflowValidator(node_registry=_StubNodeRegistry())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="output_1", type="output/mock", config={}),
            WorkflowNode(id="input_1", type="input/mock", config={"file": "$file_0"}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="output_1", target="input_1"),
            WorkflowConnection(source="input_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False


def test_validator_accepts_adaptor_and_iteration_required_config_shapes() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "doc", "selector": ["input_1", "binary"]}],
                },
            ),
            WorkflowNode(
                id="iteration_1",
                type="processor/iteration",
                config={
                    "engine_node_type": "engine/ocr",
                    "engine_config": {},
                    "iterate_over": "binary",
                    "item_input_port": "images",
                    "mode": "sequential",
                    "max_concurrency": 1,
                    "error_handling": "terminate",
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="iteration_1"),
            WorkflowConnection(source="iteration_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is True
    assert all(error.code != "MISSING_REQUIRED_CONFIG" for error in result.errors)


def test_validator_does_not_require_provider_for_adaptor_or_iteration_nodes() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
            ),
            WorkflowNode(
                id="iteration_1",
                type="processor/iteration",
                config={
                    "engine_node_type": "engine/ocr",
                    "engine_config": {},
                    "iterate_over": "binary",
                    "item_input_port": "images",
                    "mode": "sequential",
                    "max_concurrency": 1,
                    "error_handling": "terminate",
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="iteration_1"),
            WorkflowConnection(source="iteration_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is True
    assert all(error.code != "PROVIDER_NOT_FOUND" for error in result.errors)
    assert all(error.code != "MISSING_PROVIDER" for error in result.errors)


def test_validator_accepts_universal_mime_for_adaptor_and_iteration() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'binary': b'x'}"},
            ),
            WorkflowNode(
                id="iteration_1",
                type="processor/iteration",
                config={
                    "engine_node_type": "engine/ocr",
                    "engine_config": {},
                    "iterate_over": "binary",
                    "item_input_port": "images",
                    "mode": "sequential",
                    "max_concurrency": 1,
                    "error_handling": "terminate",
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="iteration_1"),
            WorkflowConnection(source="iteration_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is True
    assert all(error.code != "TYPE_INCOMPATIBLE" for error in result.errors)


def test_validator_accepts_adaptor_output_routed_to_end() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is True
    assert all(error.code != "TYPE_INCOMPATIBLE" for error in result.errors)


def test_validator_rejects_duplicate_adaptor_binding_names() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [
                        {"name": "dup", "selector": ["input_1", "text"]},
                        {"name": "dup", "selector": ["input_1", "metadata"]},
                    ],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_DUPLICATE_NAME")
    assert issue.node_id == "adaptor_1"
    assert issue.field == "config.input_bindings"


def test_validator_rejects_duplicate_adaptor_binding_names_after_whitespace_normalization() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [
                        {"name": "dup", "selector": ["input_1", "text"]},
                        {"name": " dup ", "selector": ["input_1", "metadata"]},
                    ],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_DUPLICATE_NAME")
    assert issue.node_id == "adaptor_1"


def test_validator_rejects_non_ancestor_adaptor_binding_source() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="sibling_1", type="engine/text", config={}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "bad", "selector": ["sibling_1", "text"]}],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_NOT_ANCESTOR")
    assert issue.node_id == "adaptor_1"
    assert issue.details["selector"] == ["sibling_1", "text"]


def test_validator_rejects_invalid_adaptor_selector_grammar() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "bad", "selector": ["input_1", "binary", "0"]}],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_INVALID_SELECTOR")
    assert issue.node_id == "adaptor_1"
    assert issue.field == "config.input_bindings[0].selector"


def test_validator_rejects_empty_nested_selector_segment() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [
                        {"name": "bad", "selector": ["input_1", "structured", "", "hero"]}
                    ],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_INVALID_SELECTOR")
    assert issue.node_id == "adaptor_1"


@pytest.mark.parametrize("input_mode", ["", "bogus_mode"])
def test_validator_rejects_invalid_adaptor_input_mode(input_mode: str) -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": input_mode,
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_INVALID_MODE")
    assert issue.node_id == "adaptor_1"
    assert issue.field == "config.input_mode"


@pytest.mark.parametrize("input_mode", ["", "bogus_mode"])
def test_validator_rejects_invalid_adaptor_input_mode_even_with_bindings(input_mode: str) -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": input_mode,
                    "input_bindings": [{"name": "doc", "selector": ["input_1", "text"]}],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_INVALID_MODE")
    assert issue.node_id == "adaptor_1"


def test_validator_rejects_malformed_adaptor_binding_objects() -> None:
    validator = WorkflowValidator(node_registry=NodeRegistryService())
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={
                    "code": "def main(inputs): return {}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "broken"}],
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="end_1"),
        ],
    )

    result = validator.validate(definition)

    assert result.valid is False
    issue = next(error for error in result.errors if error.code == "BINDING_INVALID_OBJECT")
    assert issue.node_id == "adaptor_1"
