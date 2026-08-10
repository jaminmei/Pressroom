from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowDefinition
from app.services.adaptor_bindings import (
    BindingResolutionError,
    BindingSpec,
    clone_node_output,
    project_named_bindings,
)
from app.services.iteration_runtime import build_iteration_runtime_input
from app.services.iteration_scope import TrustedIterationScope

_VALID_INPUT_MODES = {"all_upstream", "custom_bindings"}


def validate_input_mode(input_mode: str) -> str:
    if input_mode not in _VALID_INPUT_MODES:
        raise BindingResolutionError(
            message="invalid input mode",
            binding_name="_mode",
            selector=[],
        )
    return input_mode


def _safe_binding_error(binding: object) -> tuple[str, list[str]]:
    if not isinstance(binding, dict):
        return "_invalid", []

    raw_name = binding.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        binding_name = raw_name.strip()
    else:
        binding_name = "_invalid"

    raw_selector = binding.get("selector")
    if isinstance(raw_selector, list):
        selector = [segment for segment in raw_selector if isinstance(segment, str)]
    else:
        selector = []

    return binding_name, selector


def compute_ancestor_closure(definition: WorkflowDefinition, target_node_id: str) -> set[str]:
    reverse_edges: dict[str, set[str]] = defaultdict(set)
    for connection in definition.connections:
        reverse_edges[connection.target].add(connection.source)

    ancestors: set[str] = set()
    pending = list(reverse_edges.get(target_node_id, set()))
    while pending:
        current = pending.pop()
        if current in ancestors:
            continue
        ancestors.add(current)
        pending.extend(reverse_edges.get(current, set()) - ancestors)

    return ancestors


def collect_visible_ancestor_outputs(
    *,
    target_node_id: str,
    target_parent_node_id: str | None = None,
    definition: WorkflowDefinition,
    completed_outputs: dict[str, NodeOutput],
) -> dict[str, NodeOutput]:
    ancestor_node_ids = compute_ancestor_closure(
        definition,
        target_parent_node_id or target_node_id,
    )
    return {
        node_id: completed_outputs[node_id]
        for node_id in sorted(ancestor_node_ids)
        if node_id in completed_outputs
    }


def _resolve_iteration_scope_value(
    *,
    trusted_scope: TrustedIterationScope,
    selector: list[str],
) -> Any:
    if len(selector) < 2 or selector[0] != trusted_scope.owner_node_id:
        raise KeyError("selector source is not visible")
    if selector[1] == "item":
        current: Any = trusted_scope.item
    elif selector[1] == "index":
        current = trusted_scope.index
    else:
        raise KeyError("selector source is not visible")

    for segment in selector[2:]:
        if not isinstance(current, dict) or segment not in current:
            raise KeyError("selector path is missing")
        current = current[segment]
    return current


def _project_iteration_scope_output(selector: list[str], value: Any) -> NodeOutput:
    if selector[1] == "item" and len(selector) == 2:
        iterate_over = "binary" if isinstance(value, BinaryRef) else "structured.elements"
        return build_iteration_runtime_input(value, iterate_over=iterate_over, port_name="item")[
            "item"
        ].model_copy(
            update={
                "metadata": {
                    "_binding_source": {
                        "node_id": selector[0],
                        "output_path": selector[1:],
                    }
                }
            }
        )
    return NodeOutput(
        structured={"value": deepcopy(value)} if not isinstance(value, dict) else deepcopy(value),
        metadata={
            "_binding_source": {
                "node_id": selector[0],
                "output_path": selector[1:],
            }
        },
    )


def resolve_adaptor_inputs(
    *,
    definition: WorkflowDefinition,
    target_node_id: str,
    target_parent_node_id: str | None = None,
    completed_outputs: dict[str, NodeOutput],
    input_mode: str = "all_upstream",
    bindings: list[dict[str, object]] | None = None,
    trusted_scope: TrustedIterationScope | None = None,
) -> dict[str, NodeOutput]:
    effective_mode = validate_input_mode(input_mode)

    visible_outputs = collect_visible_ancestor_outputs(
        target_node_id=target_node_id,
        target_parent_node_id=target_parent_node_id,
        definition=definition,
        completed_outputs=completed_outputs,
    )

    if effective_mode == "custom_bindings":
        if not bindings:
            raise BindingResolutionError(
                message="custom_bindings mode requires at least one binding",
                binding_name="_mode",
                selector=[],
            )
        binding_specs: list[BindingSpec] = []
        for item in bindings:
            try:
                binding_specs.append(BindingSpec.model_validate(item))
            except ValidationError as exc:
                binding_name, selector = _safe_binding_error(item)
                raise BindingResolutionError(
                    message="invalid binding specification",
                    binding_name=binding_name,
                    selector=selector,
                ) from exc
        scope_bindings: list[BindingSpec] = []
        normal_bindings: list[BindingSpec] = []
        scope_owner_id = trusted_scope.owner_node_id if trusted_scope is not None else None
        for binding in binding_specs:
            is_iteration_scope_selector = len(binding.selector) >= 2 and binding.selector[1] in {
                "item",
                "index",
            }
            if is_iteration_scope_selector and trusted_scope is None:
                raise BindingResolutionError(
                    message="selector source is not visible",
                    binding_name=binding.name,
                    selector=binding.selector,
                )
            if is_iteration_scope_selector and binding.selector[0] != scope_owner_id:
                raise BindingResolutionError(
                    message="selector source is not visible",
                    binding_name=binding.name,
                    selector=binding.selector,
                )
            if is_iteration_scope_selector:
                scope_bindings.append(binding)
            else:
                normal_bindings.append(binding)

        resolved_inputs = project_named_bindings(normal_bindings, visible_outputs)
        for binding in scope_bindings:
            if trusted_scope is None:
                raise BindingResolutionError(
                    message="selector source is not visible",
                    binding_name=binding.name,
                    selector=binding.selector,
                )
            try:
                value = _resolve_iteration_scope_value(
                    trusted_scope=trusted_scope,
                    selector=binding.selector,
                )
            except KeyError as exc:
                raise BindingResolutionError(
                    message=exc.args[0] if exc.args else "selector source is not visible",
                    binding_name=binding.name,
                    selector=binding.selector,
                ) from exc
            resolved_inputs[binding.name] = _project_iteration_scope_output(
                binding.selector,
                value,
            )
        return resolved_inputs

    resolved_outputs: dict[str, NodeOutput] = {}
    for node_id, output in visible_outputs.items():
        metadata = deepcopy(output.metadata)
        metadata["_binding_source"] = {"node_id": node_id, "output_path": ["$"]}
        resolved_outputs[node_id] = clone_node_output(output).model_copy(
            update={"metadata": metadata}
        )
    return resolved_outputs


__all__ = [
    "collect_visible_ancestor_outputs",
    "compute_ancestor_closure",
    "resolve_adaptor_inputs",
    "validate_input_mode",
]
