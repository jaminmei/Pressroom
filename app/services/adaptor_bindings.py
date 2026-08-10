from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.models.execution import BinaryRef, NodeOutput

_ALLOWED_TOP_LEVEL_FIELDS = {"text", "binary", "metadata", "structured"}
_RESERVED_SEGMENTS = {"item", "index"}
_INVALID_SEGMENT_PATTERN = re.compile(r"[.\[\]]")
_NUMERIC_SEGMENT_PATTERN = re.compile(r"\d+")


class BindingSpec(BaseModel):
    name: str = Field(min_length=1)
    selector: list[str] = Field(min_length=2)


@dataclass
class BindingResolutionError(ValueError):
    message: str
    binding_name: str
    selector: list[str]

    def __post_init__(self) -> None:
        super().__init__(self.message)


def validate_binding_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("binding name must be a non-empty string")
    return normalized


def validate_selector(selector: list[str]) -> None:
    if len(selector) < 2:
        raise ValueError("selector must include a top-level field")

    top_level = selector[1]
    if top_level not in _ALLOWED_TOP_LEVEL_FIELDS:
        raise ValueError(f"unknown top-level field: {top_level}")

    if top_level in {"text", "binary"} and len(selector) > 2:
        raise ValueError(f"{top_level} bindings do not support nested selectors")

    for segment in selector[2:]:
        if not segment:
            raise ValueError("invalid selector segment")
        if segment in _RESERVED_SEGMENTS:
            raise ValueError("reserved path segment is not allowed")
        if _NUMERIC_SEGMENT_PATTERN.fullmatch(segment):
            raise ValueError("numeric indexing is not supported")
        if _INVALID_SEGMENT_PATTERN.search(segment):
            raise ValueError("invalid selector segment")


def _walk_selector(output: NodeOutput, selector: list[str]) -> Any:
    validate_selector(selector)

    top_level = selector[1]
    if top_level == "text":
        return output.text
    if top_level == "binary":
        return output.binary

    current: Any = output.metadata if top_level == "metadata" else output.structured
    for segment in selector[2:]:
        if not isinstance(current, dict):
            raise KeyError("selector path requires a dictionary value")
        if segment not in current:
            raise KeyError("selector path is missing")
        current = current[segment]

    return current


def _binding_source(selector: list[str]) -> dict[str, object]:
    return {
        "node_id": selector[0],
        "output_path": selector[1:],
    }


def clone_node_output(output: NodeOutput) -> NodeOutput:
    return output.model_copy(deep=True)


def _project_value(binding_name: str, selector: list[str], value: Any) -> NodeOutput:
    top_level = selector[1]
    source_metadata = {"_binding_source": _binding_source(selector)}

    if top_level == "text":
        if value is not None and not isinstance(value, str):
            raise BindingResolutionError(
                message="text binding resolved to a non-string value",
                binding_name=binding_name,
                selector=selector,
            )
        return NodeOutput(text=deepcopy(value), metadata=source_metadata)

    if top_level == "binary":
        if not isinstance(value, list):
            raise BindingResolutionError(
                message="binary binding resolved to a non-list value",
                binding_name=binding_name,
                selector=selector,
            )
        return NodeOutput(
            binary=[BinaryRef.model_validate(item).model_copy(deep=True) for item in value],
            metadata=source_metadata,
        )

    if top_level == "metadata":
        if len(selector) == 2:
            if not isinstance(value, dict):
                raise BindingResolutionError(
                    message="metadata binding resolved to a non-dictionary value",
                    binding_name=binding_name,
                    selector=selector,
                )
            metadata = deepcopy(value)
        else:
            metadata = {selector[-1]: deepcopy(value)}
        metadata["_binding_source"] = _binding_source(selector)
        return NodeOutput(metadata=metadata)

    if len(selector) == 2:
        if not isinstance(value, dict):
            raise BindingResolutionError(
                message="structured binding resolved to a non-dictionary value",
                binding_name=binding_name,
                selector=selector,
            )
        structured = deepcopy(value)
    elif isinstance(value, dict):
        structured = deepcopy(value)
    else:
        structured = {selector[-1]: deepcopy(value)}
    return NodeOutput(structured=structured, metadata=source_metadata)


def project_named_bindings(
    bindings: list[BindingSpec],
    visible_outputs: dict[str, NodeOutput],
) -> dict[str, NodeOutput]:
    resolved: dict[str, NodeOutput] = {}
    seen_names: set[str] = set()

    for binding in bindings:
        binding_name = validate_binding_name(binding.name)
        if binding_name in seen_names:
            raise BindingResolutionError(
                message="duplicate binding name",
                binding_name=binding_name,
                selector=binding.selector,
            )
        seen_names.add(binding_name)

        try:
            validate_selector(binding.selector)
        except ValueError as exc:
            raise BindingResolutionError(
                message=str(exc),
                binding_name=binding_name,
                selector=binding.selector,
            ) from exc

        source_node_id = binding.selector[0]
        if source_node_id not in visible_outputs:
            raise BindingResolutionError(
                message="selector source is not visible",
                binding_name=binding_name,
                selector=binding.selector,
            )

        try:
            value = _walk_selector(visible_outputs[source_node_id], binding.selector)
        except KeyError as exc:
            raise BindingResolutionError(
                message=exc.args[0] if exc.args else "selector path is missing",
                binding_name=binding_name,
                selector=binding.selector,
            ) from exc

        resolved[binding_name] = _project_value(binding_name, binding.selector, value)

    return resolved


__all__ = [
    "BindingResolutionError",
    "BindingSpec",
    "clone_node_output",
    "project_named_bindings",
    "validate_binding_name",
    "validate_selector",
]
