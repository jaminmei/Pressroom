from __future__ import annotations

import pytest

from app.models.execution import BinaryRef, NodeOutput
from app.services.adaptor_bindings import (
    BindingResolutionError,
    BindingSpec,
    project_named_bindings,
)


def _state() -> dict[str, NodeOutput]:
    return {
        "input_1": NodeOutput(
            text="source text",
            binary=[BinaryRef(data="aGVsbG8=", mime_type="image/png", size_bytes=5)],
            metadata={"source": {"filename": "doc.png"}},
            structured={
                "elements": {
                    "first": {"label": "A"},
                    "second": {"label": "B"},
                }
            },
        ),
        "layout_1": NodeOutput(
            structured={"elements": {"hero": {"text": "headline"}}},
            metadata={"page": {"index": 0}},
        ),
        "sibling_1": NodeOutput(text="must stay hidden"),
    }


def test_project_named_bindings_projects_binary_text_and_dict_paths() -> None:
    resolved = project_named_bindings(
        bindings=[
            BindingSpec(name="doc", selector=["input_1", "binary"]),
            BindingSpec(name="headline", selector=["layout_1", "structured", "elements", "hero"]),
            BindingSpec(name="page_meta", selector=["layout_1", "metadata", "page"]),
            BindingSpec(name="raw_text", selector=["input_1", "text"]),
        ],
        visible_outputs=_state(),
    )

    assert resolved["doc"].binary[0].mime_type == "image/png"
    assert resolved["raw_text"].text == "source text"
    assert resolved["headline"].structured == {"text": "headline"}
    assert resolved["page_meta"].metadata["page"] == {"index": 0}
    assert resolved["headline"].metadata["_binding_source"] == {
        "node_id": "layout_1",
        "output_path": ["structured", "elements", "hero"],
    }


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        (["input_1"], "selector must include a top-level field"),
        (["input_1", "item"], "unknown top-level field"),
        (["input_1", "text", "nested"], "text bindings do not support nested selectors"),
        (["input_1", "binary", "nested"], "binary bindings do not support nested selectors"),
        (["layout_1", "structured", "elements", "0"], "numeric indexing is not supported"),
        (["layout_1", "structured", "elements", "item"], "reserved path segment is not allowed"),
        (["layout_1", "structured.malicious"], "unknown top-level field"),
        (["layout_1", "structured", "elements[0]"], "invalid selector segment"),
        (["layout_1", "structured", "", "hero"], "invalid selector segment"),
    ],
)
def test_project_named_bindings_rejects_unsafe_selector_grammar(
    selector: list[str], message: str
) -> None:
    with pytest.raises(BindingResolutionError, match=message):
        project_named_bindings(
            bindings=[BindingSpec.model_construct(name="bad", selector=selector)],
            visible_outputs=_state(),
        )


def test_project_named_bindings_rejects_duplicate_binding_names() -> None:
    with pytest.raises(BindingResolutionError, match="duplicate binding name"):
        project_named_bindings(
            bindings=[
                BindingSpec(name="dup", selector=["input_1", "text"]),
                BindingSpec(name="dup", selector=["layout_1", "structured"]),
            ],
            visible_outputs=_state(),
        )


def test_project_named_bindings_rejects_duplicate_binding_names_after_trim() -> None:
    with pytest.raises(BindingResolutionError, match="duplicate binding name"):
        project_named_bindings(
            bindings=[
                BindingSpec(name="dup", selector=["input_1", "text"]),
                BindingSpec(name=" dup ", selector=["layout_1", "structured"]),
            ],
            visible_outputs=_state(),
        )


def test_project_named_bindings_rejects_missing_node_without_leaking_content() -> None:
    with pytest.raises(BindingResolutionError) as exc_info:
        project_named_bindings(
            bindings=[BindingSpec(name="missing", selector=["missing", "text"])],
            visible_outputs=_state(),
        )

    assert exc_info.value.message == "selector source is not visible"
    assert "source text" not in str(exc_info.value)
    assert "must stay hidden" not in str(exc_info.value)


def test_project_named_bindings_rejects_missing_nested_dict_path_without_leaking_content() -> None:
    with pytest.raises(BindingResolutionError) as exc_info:
        project_named_bindings(
            bindings=[
                BindingSpec(
                    name="missing_path",
                    selector=["layout_1", "structured", "elements", "unknown"],
                )
            ],
            visible_outputs=_state(),
        )

    assert exc_info.value.message == "selector path is missing"
    assert "headline" not in str(exc_info.value)
    assert "source text" not in str(exc_info.value)


def test_project_named_bindings_rejects_non_dict_nested_walks() -> None:
    with pytest.raises(
        BindingResolutionError,
        match="selector path requires a dictionary value",
    ):
        project_named_bindings(
            bindings=[
                BindingSpec(
                    name="bad_walk",
                    selector=["input_1", "metadata", "source", "filename", "x"],
                )
            ],
            visible_outputs=_state(),
        )


def test_project_named_bindings_returns_deep_copies_for_projected_payloads() -> None:
    state = _state()
    resolved = project_named_bindings(
        bindings=[
            BindingSpec(name="doc", selector=["input_1", "binary"]),
            BindingSpec(name="raw_text", selector=["input_1", "text"]),
            BindingSpec(name="page_meta", selector=["layout_1", "metadata", "page"]),
            BindingSpec(name="headline", selector=["layout_1", "structured", "elements", "hero"]),
        ],
        visible_outputs=state,
    )

    resolved["doc"].binary[0].mime_type = "image/jpeg"
    resolved["raw_text"].text = "mutated"
    resolved["page_meta"].metadata["page"]["index"] = 99
    resolved["headline"].structured["text"] = "changed"

    assert state["input_1"].binary[0].mime_type == "image/png"
    assert state["input_1"].text == "source text"
    assert state["layout_1"].metadata["page"]["index"] == 0
    assert state["layout_1"].structured["elements"]["hero"]["text"] == "headline"
