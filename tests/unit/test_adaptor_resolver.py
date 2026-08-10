from __future__ import annotations

import pytest

from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.adaptor_bindings import BindingResolutionError
from app.services.adaptor_resolver import (
    collect_visible_ancestor_outputs,
    compute_ancestor_closure,
    resolve_adaptor_inputs,
)


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(id="layout_1", type="processor/layout_detection", config={}),
            WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
            WorkflowNode(id="adaptor_1", type="processor/adaptor", config={"code": "pass"}),
            WorkflowNode(id="sibling_1", type="engine/text", config={}),
            WorkflowNode(id="downstream_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="layout_1"),
            WorkflowConnection(source="layout_1", target="ocr_1"),
            WorkflowConnection(source="ocr_1", target="adaptor_1"),
            WorkflowConnection(source="adaptor_1", target="downstream_1"),
            WorkflowConnection(source="input_1", target="sibling_1"),
        ],
    )


def _state() -> dict[str, NodeOutput]:
    return {
        "input_1": NodeOutput(
            binary=[BinaryRef(data="aGVsbG8=", mime_type="image/png", size_bytes=5)]
        ),
        "layout_1": NodeOutput(structured={"elements": {"hero": {"text": "headline"}}}),
        "ocr_1": NodeOutput(text="recognized text"),
        "sibling_1": NodeOutput(text="hidden"),
        "downstream_1": NodeOutput(text="downstream"),
    }


def test_compute_ancestor_closure_returns_only_upstream_nodes() -> None:
    assert compute_ancestor_closure(_definition(), "adaptor_1") == {
        "input_1",
        "layout_1",
        "ocr_1",
    }


def test_collect_visible_ancestor_outputs_filters_to_present_ancestors_and_sorts_keys() -> None:
    visible = collect_visible_ancestor_outputs(
        target_node_id="adaptor_1",
        definition=_definition(),
        completed_outputs=_state(),
    )

    assert list(visible) == ["input_1", "layout_1", "ocr_1"]
    assert "sibling_1" not in visible
    assert "downstream_1" not in visible
    assert visible["ocr_1"].text == "recognized text"


def test_resolve_adaptor_inputs_all_upstream_only_exposes_ancestor_outputs() -> None:
    resolved = resolve_adaptor_inputs(
        definition=_definition(),
        target_node_id="adaptor_1",
        completed_outputs=_state(),
        input_mode="all_upstream",
    )

    assert list(resolved) == ["input_1", "layout_1", "ocr_1"]
    assert resolved["ocr_1"].metadata["_binding_source"] == {
        "node_id": "ocr_1",
        "output_path": ["$"],
    }


def test_resolve_adaptor_inputs_custom_bindings_uses_same_visible_ancestor_rules() -> None:
    resolved = resolve_adaptor_inputs(
        definition=_definition(),
        target_node_id="adaptor_1",
        completed_outputs=_state(),
        input_mode="custom_bindings",
        bindings=[
            {"name": "image", "selector": ["input_1", "binary"]},
            {"name": "text", "selector": ["ocr_1", "text"]},
        ],
    )

    assert list(resolved) == ["image", "text"]
    assert resolved["image"].binary[0].mime_type == "image/png"
    assert resolved["text"].text == "recognized text"


def test_resolve_adaptor_inputs_rejects_non_ancestor_binding_sources() -> None:
    with pytest.raises(BindingResolutionError, match="selector source is not visible"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode="custom_bindings",
            bindings=[{"name": "bad", "selector": ["sibling_1", "text"]}],
        )


def test_resolve_adaptor_inputs_rejects_empty_custom_bindings() -> None:
    with pytest.raises(
        BindingResolutionError,
        match="custom_bindings mode requires at least one binding",
    ):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode="custom_bindings",
            bindings=[],
        )


def test_resolve_adaptor_inputs_uses_custom_mode_when_bindings_exist() -> None:
    with pytest.raises(BindingResolutionError, match="invalid input mode"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode="",
            bindings=[{"name": "doc", "selector": ["input_1", "binary"]}],
        )


@pytest.mark.parametrize("input_mode", ["", "bogus_mode"])
def test_resolve_adaptor_inputs_rejects_invalid_mode_without_bindings(input_mode: str) -> None:
    with pytest.raises(BindingResolutionError, match="invalid input mode"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode=input_mode,
            bindings=None,
        )


@pytest.mark.parametrize("input_mode", ["", "bogus_mode"])
def test_resolve_adaptor_inputs_rejects_invalid_mode_with_bindings(input_mode: str) -> None:
    with pytest.raises(BindingResolutionError, match="invalid input mode"):
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode=input_mode,
            bindings=[{"name": "doc", "selector": ["input_1", "binary"]}],
        )


@pytest.mark.parametrize(
    ("binding", "binding_name", "selector"),
    [
        ({"name": "broken"}, "broken", []),
        ({"name": "broken", "selector": "text"}, "broken", []),
        ({"name": "broken", "selector": ["input_1", 7]}, "broken", ["input_1"]),
        ({"name": 12, "selector": ["input_1", "text"]}, "_invalid", ["input_1", "text"]),
    ],
)
def test_resolve_adaptor_inputs_wraps_bindingspec_validation_errors_safely(
    binding: dict[str, object], binding_name: str, selector: list[str]
) -> None:
    with pytest.raises(BindingResolutionError) as exc_info:
        resolve_adaptor_inputs(
            definition=_definition(),
            target_node_id="adaptor_1",
            completed_outputs=_state(),
            input_mode="custom_bindings",
            bindings=[binding],
        )

    assert exc_info.value.message == "invalid binding specification"
    assert exc_info.value.binding_name == binding_name
    assert exc_info.value.selector == selector
    assert "ValidationError" not in str(exc_info.value)
    assert "recognized text" not in str(exc_info.value)


def test_resolve_adaptor_inputs_all_upstream_returns_deep_copies() -> None:
    state = _state()
    resolved = resolve_adaptor_inputs(
        definition=_definition(),
        target_node_id="adaptor_1",
        completed_outputs=state,
        input_mode="all_upstream",
    )

    resolved["input_1"].binary[0].mime_type = "image/jpeg"
    resolved["layout_1"].structured["elements"]["hero"]["text"] = "changed"
    resolved["ocr_1"].text = "mutated"

    assert state["input_1"].binary[0].mime_type == "image/png"
    assert state["layout_1"].structured["elements"]["hero"]["text"] == "headline"
    assert state["ocr_1"].text == "recognized text"
