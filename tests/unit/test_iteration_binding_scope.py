from __future__ import annotations

import pytest

from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.adaptor_bindings import BindingResolutionError
from app.services.adaptor_resolver import resolve_adaptor_inputs
from app.services.iteration_scope import TrustedIterationScope


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition(
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
                        "input_bindings": [],
                    },
                },
            ),
            WorkflowNode(id="sibling_1", type="engine/text", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="ocr_1", target_port="images"),
            WorkflowConnection(source="ocr_1", target="iter_1", target_port="input"),
            WorkflowConnection(source="input_1", target="sibling_1", target_port="text"),
        ],
    )


def _completed_outputs() -> dict[str, NodeOutput]:
    return {
        "input_1": NodeOutput(text="input text"),
        "ocr_1": NodeOutput(text="ancestor output"),
        "iter_1": NodeOutput(metadata={"_iteration_scope": True, "_iteration_item": "spoof"}),
        "sibling_1": NodeOutput(text="hidden sibling"),
    }


def test_custom_bindings_allow_trusted_item_index_and_ancestors_only() -> None:
    resolved = resolve_adaptor_inputs(
        definition=_definition(),
        target_node_id="iter_1__item_0",
        target_parent_node_id="iter_1",
        completed_outputs=_completed_outputs(),
        input_mode="custom_bindings",
        bindings=[
            {"name": "ancestor", "selector": ["ocr_1", "text"]},
            {"name": "item", "selector": ["iter_1", "item"]},
            {"name": "index", "selector": ["iter_1", "index"]},
        ],
        trusted_scope=TrustedIterationScope(
            owner_node_id="iter_1",
            item=BinaryRef(data="aGVsbG8=", mime_type="image/png", size_bytes=5),
            index=3,
        ),
    )

    assert resolved["ancestor"].text == "ancestor output"
    assert resolved["item"].binary[0].data == "aGVsbG8="
    assert resolved["index"].structured == {"value": 3}


def test_plain_metadata_cannot_spoof_iteration_scope() -> None:
    with pytest.raises(BindingResolutionError, match="selector source is not visible"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="iter_1",
            completed_outputs=_completed_outputs(),
            input_mode="custom_bindings",
            bindings=[{"name": "item", "selector": ["iter_1", "item"]}],
        )


def test_all_upstream_mode_never_exposes_item_or_index_scope() -> None:
    resolved = resolve_adaptor_inputs(
        definition=_definition(),
        target_node_id="iter_1__item_0",
        target_parent_node_id="iter_1",
        completed_outputs=_completed_outputs(),
        input_mode="all_upstream",
        trusted_scope=TrustedIterationScope(owner_node_id="iter_1", item={"value": "x"}, index=1),
    )

    assert list(resolved) == ["input_1", "ocr_1"]
    assert "iter_1" not in resolved


def test_iteration_scope_rejects_wrong_owner_and_non_ancestor_visibility() -> None:
    with pytest.raises(BindingResolutionError, match="selector source is not visible"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="iter_1__item_0",
            target_parent_node_id="iter_1",
            completed_outputs=_completed_outputs(),
            input_mode="custom_bindings",
            bindings=[{"name": "item", "selector": ["wrong_iter", "item"]}],
            trusted_scope=TrustedIterationScope(owner_node_id="iter_1", item="x", index=0),
        )

    with pytest.raises(BindingResolutionError, match="selector source is not visible"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="iter_1__item_0",
            target_parent_node_id="iter_1",
            completed_outputs=_completed_outputs(),
            input_mode="custom_bindings",
            bindings=[{"name": "sibling", "selector": ["sibling_1", "text"]}],
            trusted_scope=TrustedIterationScope(owner_node_id="iter_1", item="x", index=0),
        )
