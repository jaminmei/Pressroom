from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import WorkflowValidator


def _validator() -> WorkflowValidator:
    return WorkflowValidator(NodeRegistryService())


def test_validator_rejects_nested_iteration_and_invalid_ranges() -> None:
    result = _validator().validate(
        WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
                WorkflowNode(
                    id="iter_1",
                    type="processor/iteration",
                    config={
                        "engine_node_type": "processor/iteration",
                        "engine_config": {},
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "parallel",
                        "max_concurrency": 11,
                        "error_handling": "terminate",
                    },
                ),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="iter_1", target_port="input"),
                WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
            ],
        )
    )

    codes = {error.code for error in result.errors}
    assert "ITERATION_INVALID_CONFIG" in codes


def test_validator_rejects_unknown_inner_node_type_and_missing_required_inner_config() -> None:
    result = _validator().validate(
        WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
                WorkflowNode(
                    id="iter_1",
                    type="processor/iteration",
                    config={
                        "engine_node_type": "engine/unknown",
                        "engine_config": {},
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "sequential",
                        "max_concurrency": 5,
                        "error_handling": "terminate",
                    },
                ),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="iter_1", target_port="input"),
                WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
            ],
        )
    )

    fields = {error.field for error in result.errors}
    assert "config.engine_node_type" in fields

    adaptor_missing_code = _validator().validate(
        WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
                WorkflowNode(
                    id="iter_1",
                    type="processor/iteration",
                    config={
                        "engine_node_type": "processor/adaptor",
                        "engine_config": {},
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "sequential",
                        "max_concurrency": 5,
                        "error_handling": "terminate",
                    },
                ),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="iter_1", target_port="input"),
                WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
            ],
        )
    )

    missing_fields = {error.field for error in adaptor_missing_code.errors}
    assert "config.engine_config.code" in missing_fields


def test_validator_allows_only_item_and_index_self_selectors_for_inner_adaptor() -> None:
    result = _validator().validate(
        WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
                WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
                WorkflowNode(
                    id="iter_1",
                    type="processor/iteration",
                    config={
                        "engine_node_type": "processor/adaptor",
                        "engine_config": {
                            "code": "def main(inputs):\n    return {'text': 'ok'}",
                            "input_mode": "custom_bindings",
                            "input_bindings": [
                                {"name": "ok_item", "selector": ["iter_1", "item"]},
                                {"name": "ok_index", "selector": ["iter_1", "index"]},
                                {"name": "bad_self", "selector": ["iter_1", "text"]},
                                {"name": "bad_sibling", "selector": ["sibling_1", "text"]},
                            ],
                        },
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "sequential",
                        "max_concurrency": 5,
                        "error_handling": "terminate",
                    },
                ),
                WorkflowNode(id="sibling_1", type="engine/text", config={}),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="ocr_1", target_port="images"),
                WorkflowConnection(source="ocr_1", target="iter_1", target_port="input"),
                WorkflowConnection(source="input_1", target="sibling_1", target_port="text"),
                WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
            ],
        )
    )

    failing_fields = {error.field for error in result.errors}
    assert "config.engine_config.input_bindings[2].selector" in failing_fields
    assert "config.engine_config.input_bindings[3].selector" in failing_fields


def test_validator_rejects_duplicate_and_blank_inner_adaptor_binding_names() -> None:
    result = _validator().validate(
        WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
                WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
                WorkflowNode(
                    id="iter_1",
                    type="processor/iteration",
                    config={
                        "engine_node_type": "processor/adaptor",
                        "engine_config": {
                            "code": "def main(inputs):\n    return {'text': 'ok'}",
                            "input_mode": "custom_bindings",
                            "input_bindings": [
                                {"name": "dup", "selector": ["ocr_1", "text"]},
                                {"name": "dup", "selector": ["iter_1", "item"]},
                                {"name": "   ", "selector": ["iter_1", "index"]},
                            ],
                        },
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "sequential",
                        "max_concurrency": 5,
                        "error_handling": "terminate",
                    },
                ),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="ocr_1", target_port="images"),
                WorkflowConnection(source="ocr_1", target="iter_1", target_port="input"),
                WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
            ],
        )
    )

    fields = {error.field for error in result.errors}
    assert "config.engine_config.input_bindings[1].name" in fields
    assert "config.engine_config.input_bindings[2].name" in fields
