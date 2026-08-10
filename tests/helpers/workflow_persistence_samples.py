from __future__ import annotations

from copy import deepcopy

from app.models.workflow import WorkflowDefinition

ADAPTOR_CODE = "def main(inputs):\n    return {'text': 'adapted'}"
ITERATION_ADAPTOR_CODE = "def main(inputs):\n    return {'text': 'iterated'}"


def complex_workflow_definition_dict() -> dict[str, object]:
    return {
        "nodes": [
            {
                "id": "input_1",
                "type": "input/image",
                "config": {"file": "$file_0"},
                "position": {"x": 40, "y": 20},
            },
            {
                "id": "layout_1",
                "type": "processor/layout_detection",
                "config": {"selected_types": ["Text", "Table"]},
                "position": {"x": 180, "y": 20},
            },
            {
                "id": "adaptor_1",
                "type": "processor/adaptor",
                "config": {
                    "code": ADAPTOR_CODE,
                    "input_mode": "custom_bindings",
                    "input_bindings": [
                        {"name": "image", "selector": ["input_1", "binary"]},
                        {
                            "name": "first_region_text",
                            "selector": ["layout_1", "structured", "elements"],
                        },
                        {
                            "name": "elements",
                            "selector": ["layout_1", "structured", "elements"],
                        },
                    ],
                    "unknown_nested": {
                        "list_order": ["alpha", "beta", "gamma"],
                        "selector_like": ["layout_1", "structured", "elements", "1"],
                    },
                    "_binding_source": {"user_authored": True},
                },
                "position": {"x": 360, "y": 0},
            },
            {
                "id": "iter_1",
                "type": "processor/iteration",
                "config": {
                    "engine_node_type": "processor/adaptor",
                    "engine_config": {
                        "code": ITERATION_ADAPTOR_CODE,
                        "input_mode": "custom_bindings",
                        "input_bindings": [
                            {"name": "item", "selector": ["iter_1", "item"]},
                            {"name": "index", "selector": ["iter_1", "index"]},
                            {
                                "name": "ancestor_elements",
                                "selector": ["layout_1", "structured", "elements"],
                            },
                        ],
                        "unknown_nested": {
                            "ordered": [1, 2, 3],
                            "selector_like": ["iter_1", "item", "text"],
                        },
                        "_iteration_item": {"user_authored": True},
                        "_iteration_index": {"user_authored": True},
                    },
                    "iterate_over": "structured.elements",
                    "item_input_port": "image",
                    "mode": "parallel",
                    "max_concurrency": 3,
                    "error_handling": "remove_failed",
                    "unknown_nested": {
                        "ordered_selectors": [
                            ["layout_1", "structured", "elements", "0"],
                            ["layout_1", "structured", "elements", "1"],
                        ]
                    },
                    "_iteration_scope": {"user_authored": True},
                },
                "position": {"x": 360, "y": 140},
            },
            {
                "id": "end_1",
                "type": "end/final",
                "config": {},
                "position": {"x": 560, "y": 80},
            },
        ],
        "connections": [
            {
                "source": "layout_1",
                "target": "iter_1",
                "source_port": None,
                "target_port": "input",
            },
            {
                "source": "input_1",
                "target": "layout_1",
                "source_port": None,
                "target_port": "image",
            },
            {
                "source": "layout_1",
                "target": "adaptor_1",
                "source_port": None,
                "target_port": "input",
            },
            {
                "source": "iter_1",
                "target": "end_1",
                "source_port": None,
                "target_port": "input",
            },
        ],
    }


def complex_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(complex_workflow_definition_dict())


def complex_workflow_definition_with_top_level_extras() -> dict[str, object]:
    payload = complex_workflow_definition_dict()
    payload["top_level_extra"] = {"ignored": True}
    return payload


def runtime_metadata_keys() -> list[str]:
    return ["_binding_source", "_iteration_scope", "_iteration_item", "_iteration_index"]


def runtime_metadata_injection() -> dict[str, object]:
    return {
        "_binding_source": {"node_id": "ocr_1", "output_path": ["$"]},
        "_iteration_scope": True,
        "_iteration_item": {"text": "spoof"},
        "_iteration_index": 7,
    }


def cloned_complex_definition_dict() -> dict[str, object]:
    return deepcopy(complex_workflow_definition_dict())
