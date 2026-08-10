from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.providers.store import ProviderStore
from app.services.adaptor_bindings import (
    BindingResolutionError,
    validate_binding_name,
    validate_selector,
)
from app.services.adaptor_resolver import compute_ancestor_closure, validate_input_mode
from app.services.engine_client import _NODE_TYPE_TO_URL_KEY
from app.services.node_registry import NodeRegistryService
from app.services.topological_sort import CyclicDependencyError, build_execution_plan

if TYPE_CHECKING:
    from app.models.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Validation error exception."""

    pass


class ValidationIssue(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    severity: str = "blocking"
    node_id: str | None = None
    field: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class ValidationWarning(BaseModel):
    """A dynamic validation warning related to model capabilities."""

    code: str
    severity: Literal["warning", "info"]
    node_id: str
    message: str
    model: str | None = None


class WorkflowValidator:
    def __init__(
        self,
        node_registry: NodeRegistryService,
        provider_store: ProviderStore | None = None,
    ) -> None:
        self._node_registry = node_registry
        self._provider_store = provider_store

    def validate(
        self,
        definition: WorkflowDefinition,
        *,
        workspace_id: str | None = None,
    ) -> ValidationResult:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        errors.extend(self._check_node_ids(definition))
        errors.extend(self._check_known_node_types(definition))
        errors.extend(self._check_required_configs(definition))
        errors.extend(self._check_connection_nodes_exist(definition))
        errors.extend(self._check_required_nodes(definition))
        warnings.extend(self._check_orphan_nodes(definition))
        errors.extend(self._check_connection_rules(definition))
        errors.extend(self._check_end_node_rules(definition))
        errors.extend(self._check_adaptor_bindings(definition))
        errors.extend(self._check_iteration_nodes(definition))
        errors.extend(self._check_dag(definition))
        errors.extend(self._check_provider_ids(definition, workspace_id=workspace_id))

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_for_publish(
        self,
        definition: WorkflowDefinition,
        *,
        workspace_id: str | None = None,
    ) -> ValidationResult:
        if not definition.nodes:
            return ValidationResult(
                valid=False,
                errors=[
                    ValidationIssue(
                        code="WORKFLOW_EMPTY",
                        message="Workflow 沒有任何節點",
                        severity="blocking",
                        field="nodes",
                    )
                ],
                warnings=[],
            )

        result = self.validate(definition, workspace_id=workspace_id)
        filtered_errors = [
            e
            for e in result.errors
            if not (
                e.code == "MISSING_REQUIRED_CONFIG"
                and e.details
                and e.details.get("missing_field") == "file"
            )
        ]

        return ValidationResult(
            valid=len(filtered_errors) == 0, errors=filtered_errors, warnings=result.warnings
        )

    def validate_dynamic(self, definition: WorkflowDefinition) -> list[ValidationWarning]:
        """Run dynamic capability-aware validation.

        Returns a list of ValidationWarning objects. These do NOT block
        workflow editing but SHOULD block execution when severity == "warning".
        """
        warnings: list[ValidationWarning] = []
        nodes_by_id = {node.id: node for node in definition.nodes}
        visual_types = {"image/*", "image/cropped_blocks"}

        for node in definition.nodes:
            if node.type != "engine/model":
                continue

            selected_model_value = node.config.get("model")
            selected_model = selected_model_value if isinstance(selected_model_value, str) else None
            incoming_edges = [conn for conn in definition.connections if conn.target == node.id]

            has_visual_input = False
            for edge in incoming_edges:
                source_node = nodes_by_id.get(edge.source)
                if source_node is None:
                    continue
                source_def = self._node_registry.get_node_definition(source_node.type)
                if source_def is None:
                    continue
                for out_type in source_def.output_types:
                    if any(self._match_type(out_type, vt) for vt in visual_types):
                        has_visual_input = True
                        break
                if has_visual_input:
                    break

            if selected_model:
                meta = self._node_registry.get_model_capability(node.type, selected_model)
                if meta and "has_vision" not in meta:
                    logger.debug(
                        "Model '%s' missing has_vision metadata, defaulting to True", selected_model
                    )
                if meta and not meta.get("has_vision", True):
                    if has_visual_input:
                        warnings.append(
                            ValidationWarning(
                                code="MODEL_NO_VISION",
                                severity="warning",
                                node_id=node.id,
                                message=(
                                    f"Model '"
                                    f"{meta.get('display_name', selected_model)}"
                                    f"' does not support vision input, "
                                    f"but image edges are connected."
                                ),
                                model=selected_model,
                            )
                        )
            elif has_visual_input:
                warnings.append(
                    ValidationWarning(
                        code="MODEL_NOT_SELECTED",
                        severity="info",
                        node_id=node.id,
                        message=(
                            "No model selected. Select a vision-capable"
                            " model to process image input."
                        ),
                        model=None,
                    )
                )

        return warnings

    async def check_engine_health(self, payload: WorkflowDefinition) -> list[ValidationWarning]:
        """Check reachability of engine containers referenced in the workflow."""
        settings = get_settings()

        # Map node types to engine URLs using the canonical mapping from engine_client
        # Skip model nodes: upstream reachability belongs to the Provider test flow.
        _SKIP_HEALTH_CHECK = {"engine/model"}
        ENGINE_URL_MAP: dict[str, str] = {
            node_type: getattr(settings, url_key)
            for node_type, url_key in _NODE_TYPE_TO_URL_KEY.items()
            if node_type not in _SKIP_HEALTH_CHECK
        }

        # Collect unique engine types used in the workflow
        engine_types = {node.type for node in payload.nodes if node.type in ENGINE_URL_MAP}

        warnings: list[ValidationWarning] = []
        async with httpx.AsyncClient(timeout=3.0) as client:
            for engine_type in sorted(engine_types):
                url = ENGINE_URL_MAP[engine_type]
                try:
                    resp = await client.get(f"{url}/health")
                    if resp.status_code != 200:
                        warnings.append(
                            ValidationWarning(
                                code="ENGINE_UNREACHABLE",
                                severity="warning",
                                node_id=engine_type,
                                message=f"引擎 {engine_type} 回應異常 (HTTP {resp.status_code})",
                            )
                        )
                except (httpx.HTTPError, Exception):
                    warnings.append(
                        ValidationWarning(
                            code="ENGINE_UNREACHABLE",
                            severity="warning",
                            node_id=engine_type,
                            message=f"引擎 {engine_type} 無法連線",
                        )
                    )

        return warnings

    def _check_node_ids(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        seen: set[str] = set()
        errors: list[ValidationIssue] = []

        for node in definition.nodes:
            if node.id in seen:
                errors.append(
                    ValidationIssue(
                        code="DUPLICATE_NODE_ID",
                        message=f"節點 ID 重複：{node.id}",
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="id",
                    )
                )
            seen.add(node.id)

        return errors

    def _check_known_node_types(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []

        for node in definition.nodes:
            if self._node_registry.get_node_definition(node.type) is None:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_NODE_TYPE",
                        message=f"未知的節點類型：{node.type}",
                        details={"node_id": node.id, "node_type": node.type},
                        severity="blocking",
                        node_id=node.id,
                        field="type",
                    )
                )

        return errors

    def _check_required_configs(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []

        for node in definition.nodes:
            node_def = self._node_registry.get_node_definition(node.type)
            if node_def is None:
                continue

            required_fields = node_def.config_schema.get("required", [])
            if not isinstance(required_fields, list):
                continue

            for field_name in required_fields:
                if field_name not in node.config:
                    errors.append(
                        ValidationIssue(
                            code="MISSING_REQUIRED_CONFIG",
                            message=f"節點 {node.id} 缺少必填欄位：{field_name}",
                            details={"node_id": node.id, "missing_field": field_name},
                            severity="blocking",
                            node_id=node.id,
                            field=f"config.{field_name}",
                        )
                    )

        return errors

    def _check_connection_nodes_exist(
        self, definition: WorkflowDefinition
    ) -> list[ValidationIssue]:
        node_ids = {node.id for node in definition.nodes}
        errors: list[ValidationIssue] = []

        for connection in definition.connections:
            if connection.source not in node_ids or connection.target not in node_ids:
                errors.append(
                    ValidationIssue(
                        code="INVALID_CONNECTION",
                        message="連線的 source/target 節點不存在",
                        details={
                            "source": connection.source,
                            "target": connection.target,
                        },
                        severity="blocking",
                        field="connections",
                    )
                )

        return errors

    def _check_required_nodes(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        has_input = any(node.type.startswith("input/") for node in definition.nodes)
        has_end = any(node.type == "end/final" for node in definition.nodes)

        errors: list[ValidationIssue] = []
        if not has_input:
            errors.append(
                ValidationIssue(
                    code="WORKFLOW_NO_INPUT",
                    message="Workflow 缺少輸入節點",
                    severity="blocking",
                    field="nodes",
                )
            )
        if not has_end:
            errors.append(
                ValidationIssue(
                    code="WORKFLOW_NO_END",
                    message="Workflow 缺少 end/final 節點",
                    severity="blocking",
                    field="nodes",
                )
            )

        return errors

    def _check_orphan_nodes(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        if len(definition.nodes) <= 1:
            return []

        connected_ids: set[str] = set()
        for connection in definition.connections:
            connected_ids.add(connection.source)
            connected_ids.add(connection.target)

        warnings: list[ValidationIssue] = []
        for node in definition.nodes:
            if node.id not in connected_ids:
                warnings.append(
                    ValidationIssue(
                        code="WORKFLOW_ORPHAN_NODE",
                        message=f"存在孤立節點：{node.id}",
                        details={"node_id": node.id},
                        severity="non-blocking",
                        node_id=node.id,
                        field="nodes",
                    )
                )

        return warnings

    def _check_connection_rules(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        node_by_id = {node.id: node for node in definition.nodes}
        outgoing_count: dict[str, int] = {node.id: 0 for node in definition.nodes}
        incoming_count: dict[str, int] = {node.id: 0 for node in definition.nodes}
        # Per-port connection counting: node_id -> {port_name -> count}
        port_connections: dict[str, dict[str, int]] = {}
        errors: list[ValidationIssue] = []

        for connection in definition.connections:
            source = node_by_id.get(connection.source)
            target = node_by_id.get(connection.target)
            if source is None or target is None:
                continue

            source_def = self._node_registry.get_node_definition(source.type)
            target_def = self._node_registry.get_node_definition(target.type)
            if source_def is None or target_def is None:
                continue

            outgoing_count[source.id] += 1
            incoming_count[target.id] += 1

            if source_def.max_outputs >= 0 and outgoing_count[source.id] > source_def.max_outputs:
                errors.append(
                    ValidationIssue(
                        code="INVALID_CONNECTION",
                        message=f"節點 {source.id} 超過最大輸出連線數",
                        details={"node_id": source.id, "max_outputs": source_def.max_outputs},
                        severity="blocking",
                        node_id=source.id,
                        field="connections",
                    )
                )

            if target_def.max_inputs >= 0 and incoming_count[target.id] > target_def.max_inputs:
                errors.append(
                    ValidationIssue(
                        code="INVALID_CONNECTION",
                        message=f"節點 {target.id} 超過最大輸入連線數",
                        details={"node_id": target.id, "max_inputs": target_def.max_inputs},
                        severity="blocking",
                        node_id=target.id,
                        field="connections",
                    )
                )

            # --- Per-port MIME validation ---
            target_port_name = connection.target_port

            # Resolve virtual frontend handle names to real port names
            if target_def.input_ports and target_port_name in ("default", "primary", "context"):
                if target_port_name == "context" and len(target_def.input_ports) > 1:
                    target_port_name = target_def.input_ports[-1].name
                else:
                    target_port_name = target_def.input_ports[0].name

            if target_def.input_ports:
                if target_port_name is not None:
                    # Explicit port: find the matching InputPortDef by name
                    port_def = next(
                        (p for p in target_def.input_ports if p.name == target_port_name),
                        None,
                    )
                    if port_def is None:
                        errors.append(
                            ValidationIssue(
                                code="UNKNOWN_PORT",
                                message=f"節點 {target.id} 沒有名為 '{target_port_name}' 的輸入埠",
                                details={
                                    "source": source.id,
                                    "target": target.id,
                                    "target_port": target_port_name,
                                    "available_ports": [p.name for p in target_def.input_ports],
                                },
                                severity="blocking",
                                node_id=target.id,
                                field="connections",
                            )
                        )
                    else:
                        # Track per-port connection count
                        node_ports = port_connections.setdefault(target.id, {})
                        node_ports[target_port_name] = node_ports.get(target_port_name, 0) + 1

                        if (
                            port_def.max_connections >= 0
                            and node_ports[target_port_name] > port_def.max_connections
                        ):
                            errors.append(
                                ValidationIssue(
                                    code="PORT_MAX_CONNECTIONS",
                                    message=(
                                        f"節點 {target.id} 的輸入埠 '{target_port_name}' "
                                        f"超過最大連線數 ({port_def.max_connections})"
                                    ),
                                    details={
                                        "node_id": target.id,
                                        "port": target_port_name,
                                        "max_connections": port_def.max_connections,
                                        "current_count": node_ports[target_port_name],
                                    },
                                    severity="blocking",
                                    node_id=target.id,
                                    field="connections",
                                )
                            )

                        # MIME compatibility: source output_types vs port accepted_types
                        if not self._is_type_compatible(
                            source_def.output_types, port_def.accepted_types
                        ):
                            errors.append(
                                ValidationIssue(
                                    code="TYPE_INCOMPATIBLE",
                                    message=(
                                        f"節點類型不相容：{source.id} -> {target.id}"
                                        f" (埠 '{target_port_name}')"
                                    ),
                                    details={
                                        "source": source.id,
                                        "target": target.id,
                                        "target_port": target_port_name,
                                        "source_outputs": source_def.output_types,
                                        "target_inputs": port_def.accepted_types,
                                    },
                                    severity="blocking",
                                    node_id=target.id,
                                    field="connections",
                                )
                            )
                else:
                    # No explicit port: auto-match — find compatible ports by MIME type
                    compatible_ports = [
                        p
                        for p in target_def.input_ports
                        if self._is_type_compatible(source_def.output_types, p.accepted_types)
                    ]
                    if not compatible_ports:
                        errors.append(
                            ValidationIssue(
                                code="TYPE_INCOMPATIBLE",
                                message=f"節點類型不相容：{source.id} -> {target.id}",
                                details={
                                    "source": source.id,
                                    "target": target.id,
                                    "source_outputs": source_def.output_types,
                                    "port_definitions": [
                                        {"port": p.name, "accepted_types": p.accepted_types}
                                        for p in target_def.input_ports
                                    ],
                                },
                                severity="blocking",
                                node_id=target.id,
                                field="connections",
                            )
                        )
                    else:
                        # Track connection on the first compatible port
                        matched_port = compatible_ports[0]
                        node_ports = port_connections.setdefault(target.id, {})
                        node_ports[matched_port.name] = node_ports.get(matched_port.name, 0) + 1

                        if (
                            matched_port.max_connections >= 0
                            and node_ports[matched_port.name] > matched_port.max_connections
                        ):
                            errors.append(
                                ValidationIssue(
                                    code="PORT_MAX_CONNECTIONS",
                                    message=(
                                        f"節點 {target.id} 的輸入埠 '{matched_port.name}' "
                                        f"超過最大連線數 ({matched_port.max_connections})"
                                    ),
                                    details={
                                        "node_id": target.id,
                                        "port": matched_port.name,
                                        "max_connections": matched_port.max_connections,
                                        "current_count": node_ports[matched_port.name],
                                    },
                                    severity="blocking",
                                    node_id=target.id,
                                    field="connections",
                                )
                            )
            else:
                # Backward compat: fall back to flat input_types when no input_ports defined
                if not self._is_type_compatible(source_def.output_types, target_def.input_types):
                    errors.append(
                        ValidationIssue(
                            code="TYPE_INCOMPATIBLE",
                            message=f"節點類型不相容：{source.id} -> {target.id}",
                            details={
                                "source": source.id,
                                "target": target.id,
                                "source_outputs": source_def.output_types,
                                "target_inputs": target_def.input_types,
                            },
                            severity="blocking",
                            node_id=target.id,
                            field="connections",
                        )
                    )

        return errors

    def _check_dag(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        try:
            build_execution_plan(definition)
            return []
        except CyclicDependencyError:
            return [
                ValidationIssue(
                    code="WORKFLOW_CYCLE",
                    message="Workflow 包含循環依賴",
                    severity="blocking",
                    field="connections",
                )
            ]

    def _check_adaptor_bindings(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        node_ids = {node.id for node in definition.nodes}

        for node in definition.nodes:
            if node.type != "processor/adaptor":
                continue

            raw_bindings = node.config.get("input_bindings", [])
            input_mode = node.config.get("input_mode", "all_upstream")
            if raw_bindings is None:
                raw_bindings = []

            if not isinstance(input_mode, str):
                errors.append(
                    ValidationIssue(
                        code="BINDING_INVALID_MODE",
                        message=f"節點 {node.id} 的 input_mode 無效",
                        details={"node_id": node.id, "input_mode": "_invalid_type"},
                        severity="blocking",
                        node_id=node.id,
                        field="config.input_mode",
                    )
                )
                continue

            try:
                validate_input_mode(input_mode)
            except BindingResolutionError:
                errors.append(
                    ValidationIssue(
                        code="BINDING_INVALID_MODE",
                        message=f"節點 {node.id} 的 input_mode 無效",
                        details={"node_id": node.id, "input_mode": input_mode},
                        severity="blocking",
                        node_id=node.id,
                        field="config.input_mode",
                    )
                )
                continue

            if not isinstance(raw_bindings, list):
                errors.append(
                    ValidationIssue(
                        code="BINDING_INVALID_OBJECT",
                        message=f"節點 {node.id} 的 input_bindings 必須是陣列",
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="config.input_bindings",
                    )
                )
                continue

            if input_mode == "custom_bindings" and not raw_bindings:
                errors.append(
                    ValidationIssue(
                        code="BINDING_INVALID_OBJECT",
                        message=f"節點 {node.id} 的 custom_bindings 模式至少需要一個 binding",
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="config.input_bindings",
                    )
                )
                continue

            ancestor_node_ids = compute_ancestor_closure(definition, node.id)
            seen_names: set[str] = set()
            for index, raw_binding in enumerate(raw_bindings):
                field_prefix = f"config.input_bindings[{index}]"
                if not isinstance(raw_binding, dict):
                    errors.append(
                        ValidationIssue(
                            code="BINDING_INVALID_OBJECT",
                            message=f"節點 {node.id} 的 binding 項目格式不正確",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=field_prefix,
                        )
                    )
                    continue

                raw_name = raw_binding.get("name")
                raw_selector = raw_binding.get("selector")
                if not isinstance(raw_name, str) or not isinstance(raw_selector, list):
                    errors.append(
                        ValidationIssue(
                            code="BINDING_INVALID_OBJECT",
                            message=f"節點 {node.id} 的 binding 必須包含 name 與 selector",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=field_prefix,
                        )
                    )
                    continue

                try:
                    binding_name = validate_binding_name(raw_name)
                except ValueError:
                    errors.append(
                        ValidationIssue(
                            code="BINDING_INVALID_OBJECT",
                            message=f"節點 {node.id} 的 binding name 不可為空",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=f"{field_prefix}.name",
                        )
                    )
                    continue

                if binding_name in seen_names:
                    errors.append(
                        ValidationIssue(
                            code="BINDING_DUPLICATE_NAME",
                            message=f"節點 {node.id} 的 binding name 重複：{binding_name}",
                            details={"node_id": node.id, "binding_name": binding_name},
                            severity="blocking",
                            node_id=node.id,
                            field="config.input_bindings",
                        )
                    )
                else:
                    seen_names.add(binding_name)

                if not raw_selector or not all(
                    isinstance(segment, str) for segment in raw_selector
                ):
                    errors.append(
                        ValidationIssue(
                            code="BINDING_INVALID_OBJECT",
                            message=f"節點 {node.id} 的 binding selector 格式不正確",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=f"{field_prefix}.selector",
                        )
                    )
                    continue

                selector = list(raw_selector)
                try:
                    validate_selector(selector)
                except ValueError as exc:
                    errors.append(
                        ValidationIssue(
                            code="BINDING_INVALID_SELECTOR",
                            message=f"節點 {node.id} 的 binding selector 無效",
                            details={
                                "node_id": node.id,
                                "binding_name": binding_name,
                                "selector": selector,
                                "reason": str(exc),
                            },
                            severity="blocking",
                            node_id=node.id,
                            field=f"{field_prefix}.selector",
                        )
                    )
                    continue

                source_node_id = selector[0]
                if source_node_id not in node_ids:
                    errors.append(
                        ValidationIssue(
                            code="BINDING_UNKNOWN_NODE",
                            message=f"節點 {node.id} 的 binding 指向不存在的節點：{source_node_id}",
                            details={
                                "node_id": node.id,
                                "binding_name": binding_name,
                                "selector": selector,
                            },
                            severity="blocking",
                            node_id=node.id,
                            field=f"{field_prefix}.selector",
                        )
                    )
                    continue

                if source_node_id == node.id or source_node_id not in ancestor_node_ids:
                    errors.append(
                        ValidationIssue(
                            code="BINDING_NOT_ANCESTOR",
                            message=f"節點 {node.id} 的 binding 來源必須是祖先節點",
                            details={
                                "node_id": node.id,
                                "binding_name": binding_name,
                                "selector": selector,
                            },
                            severity="blocking",
                            node_id=node.id,
                            field=f"{field_prefix}.selector",
                        )
                    )

        return errors

    def _check_iteration_nodes(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        node_ids = {node.id for node in definition.nodes}

        for node in definition.nodes:
            if node.type != "processor/iteration":
                continue

            config = node.config if isinstance(node.config, dict) else {}
            engine_node_type = config.get("engine_node_type")
            engine_config = config.get("engine_config", {})
            iterate_over = config.get("iterate_over", "binary")
            item_input_port = config.get("item_input_port", "image")
            mode = config.get("mode", "sequential")
            max_concurrency = config.get("max_concurrency", 5)
            error_handling = config.get("error_handling", "terminate")

            invalid_fields: list[str] = []
            inner_node_def = None
            if not isinstance(engine_node_type, str) or not engine_node_type.strip():
                invalid_fields.append("config.engine_node_type")
            elif engine_node_type == "processor/iteration":
                invalid_fields.append("config.engine_node_type")
            else:
                inner_node_def = self._node_registry.get_node_definition(engine_node_type)
                if inner_node_def is None:
                    invalid_fields.append("config.engine_node_type")
            if not isinstance(engine_config, dict):
                invalid_fields.append("config.engine_config")
            if iterate_over not in {"binary", "structured.elements"}:
                invalid_fields.append("config.iterate_over")
            if not isinstance(item_input_port, str) or not item_input_port.strip():
                invalid_fields.append("config.item_input_port")
            if mode not in {"sequential", "parallel"}:
                invalid_fields.append("config.mode")
            if (
                isinstance(max_concurrency, bool)
                or not isinstance(max_concurrency, int)
                or not 1 <= max_concurrency <= 10
            ):
                invalid_fields.append("config.max_concurrency")
            if error_handling not in {"terminate", "continue", "remove_failed"}:
                invalid_fields.append("config.error_handling")

            for field_name in invalid_fields:
                errors.append(
                    ValidationIssue(
                        code="ITERATION_INVALID_CONFIG",
                        message=f"節點 {node.id} 的 iteration 設定無效",
                        details={"node_id": node.id, "field": field_name},
                        severity="blocking",
                        node_id=node.id,
                        field=field_name,
                    )
                )

            if inner_node_def is not None and isinstance(engine_config, dict):
                required_fields = inner_node_def.config_schema.get("required", [])
                if isinstance(required_fields, list):
                    for required_field in required_fields:
                        if required_field not in engine_config:
                            errors.append(
                                ValidationIssue(
                                    code="ITERATION_INVALID_CONFIG",
                                    message=(
                                        f"節點 {node.id} 的 iteration inner config 缺少必填欄位："
                                        f"{required_field}"
                                    ),
                                    details={
                                        "node_id": node.id,
                                        "field": required_field,
                                        "engine_node_type": engine_node_type,
                                    },
                                    severity="blocking",
                                    node_id=node.id,
                                    field=f"config.engine_config.{required_field}",
                                )
                            )

            if engine_node_type != "processor/adaptor" or not isinstance(engine_config, dict):
                continue

            input_mode = engine_config.get("input_mode", "all_upstream")
            raw_bindings = engine_config.get("input_bindings", [])
            if not isinstance(input_mode, str) or input_mode not in {
                "all_upstream",
                "custom_bindings",
            }:
                errors.append(
                    ValidationIssue(
                        code="ITERATION_INVALID_CONFIG",
                        message=f"節點 {node.id} 的 iteration adaptor input_mode 無效",
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="config.engine_config.input_mode",
                    )
                )
                continue
            if not isinstance(raw_bindings, list):
                errors.append(
                    ValidationIssue(
                        code="ITERATION_INVALID_CONFIG",
                        message=f"節點 {node.id} 的 iteration adaptor input_bindings 必須是陣列",
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="config.engine_config.input_bindings",
                    )
                )
                continue
            if input_mode == "custom_bindings" and not raw_bindings:
                errors.append(
                    ValidationIssue(
                        code="ITERATION_INVALID_CONFIG",
                        message=(
                            f"節點 {node.id} 的 iteration adaptor custom_bindings "
                            "至少需要一個 binding"
                        ),
                        details={"node_id": node.id},
                        severity="blocking",
                        node_id=node.id,
                        field="config.engine_config.input_bindings",
                    )
                )
                continue

            ancestor_node_ids = compute_ancestor_closure(definition, node.id)
            seen_names: set[str] = set()
            for index, raw_binding in enumerate(raw_bindings):
                field_prefix = f"config.engine_config.input_bindings[{index}].selector"
                if not isinstance(raw_binding, dict):
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=f"節點 {node.id} 的 iteration adaptor binding 格式不正確",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=field_prefix,
                        )
                    )
                    continue
                raw_name = raw_binding.get("name")
                selector = raw_binding.get("selector")
                if not isinstance(raw_name, str):
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=f"節點 {node.id} 的 iteration adaptor binding name 無效",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=f"config.engine_config.input_bindings[{index}].name",
                        )
                    )
                    continue
                binding_name = raw_name.strip()
                if not binding_name:
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=f"節點 {node.id} 的 iteration adaptor binding name 不可為空",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=f"config.engine_config.input_bindings[{index}].name",
                        )
                    )
                    continue
                if binding_name in seen_names:
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=(
                                f"節點 {node.id} 的 iteration adaptor binding name 重複："
                                f"{binding_name}"
                            ),
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=f"config.engine_config.input_bindings[{index}].name",
                        )
                    )
                else:
                    seen_names.add(binding_name)
                if (
                    not isinstance(selector, list)
                    or not selector
                    or not all(isinstance(segment, str) for segment in selector)
                ):
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=f"節點 {node.id} 的 iteration adaptor selector 格式不正確",
                            details={"node_id": node.id, "binding_index": index},
                            severity="blocking",
                            node_id=node.id,
                            field=field_prefix,
                        )
                    )
                    continue
                source_node_id = selector[0]
                if source_node_id == node.id:
                    if len(selector) < 2 or selector[1] not in {"item", "index"}:
                        errors.append(
                            ValidationIssue(
                                code="ITERATION_INVALID_CONFIG",
                                message=(
                                    f"節點 {node.id} 的 iteration adaptor self "
                                    "selector 只允許 item/index"
                                ),
                                details={"node_id": node.id, "selector": selector},
                                severity="blocking",
                                node_id=node.id,
                                field=field_prefix,
                            )
                        )
                    continue
                if source_node_id not in node_ids or source_node_id not in ancestor_node_ids:
                    errors.append(
                        ValidationIssue(
                            code="ITERATION_INVALID_CONFIG",
                            message=(
                                f"節點 {node.id} 的 iteration adaptor selector 必須指向祖先節點"
                            ),
                            details={"node_id": node.id, "selector": selector},
                            severity="blocking",
                            node_id=node.id,
                            field=field_prefix,
                        )
                    )
                    continue

        return errors

    def _check_provider_ids(
        self,
        definition: WorkflowDefinition,
        *,
        workspace_id: str | None = None,
    ) -> list[ValidationIssue]:
        """Validate that provider_id references in engine nodes exist and are enabled."""
        if self._provider_store is None:
            return []

        errors: list[ValidationIssue] = []
        for node in definition.nodes:
            if not node.type.startswith("engine/"):
                continue
            provider_id_value = (node.config or {}).get("provider_id")
            if not isinstance(provider_id_value, str) or not provider_id_value:
                # No provider_id — backward compat, ProviderAwareAdapter will fallback
                continue
            provider_id = provider_id_value
            provider = (
                self._provider_store.get_for_runtime(provider_id, workspace_id)
                if workspace_id is not None
                else self._provider_store.get_provider(provider_id)
            )
            if provider is None:
                errors.append(
                    ValidationIssue(
                        code="PROVIDER_NOT_FOUND",
                        message=f"Provider {provider_id!r} not found",
                        node_id=node.id,
                        severity="blocking",
                        field="provider_id",
                    )
                )
            elif not provider.is_enabled:
                errors.append(
                    ValidationIssue(
                        code="PROVIDER_DISABLED",
                        message=f"Provider {provider_id!r} is disabled",
                        node_id=node.id,
                        severity="blocking",
                        field="provider_id",
                    )
                )
        return errors

    def _check_end_node_rules(self, definition: WorkflowDefinition) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        end_nodes = [node for node in definition.nodes if node.type == "end/final"]

        if len(end_nodes) > 1:
            errors.append(
                ValidationIssue(
                    code="WORKFLOW_MULTIPLE_END",
                    message="Workflow 僅允許一個 end/final 節點",
                    details={"end_node_ids": [node.id for node in end_nodes]},
                    severity="blocking",
                    field="nodes",
                )
            )
            return errors

        if not end_nodes:
            return errors

        end_node = end_nodes[0]
        outgoing_targets = [
            connection.target
            for connection in definition.connections
            if connection.source == end_node.id
        ]
        if outgoing_targets:
            errors.append(
                ValidationIssue(
                    code="END_NODE_NOT_TERMINAL",
                    message="end/final 不可有下游連線",
                    details={"node_id": end_node.id, "invalid_targets": outgoing_targets},
                    severity="blocking",
                    node_id=end_node.id,
                    field="connections",
                )
            )

        return errors

    def _is_type_compatible(self, source_outputs: list[str], target_inputs: list[str]) -> bool:
        if not target_inputs:
            return True
        for source in source_outputs:
            for target in target_inputs:
                if self._match_type(source, target):
                    return True
        return False

    def _match_type(self, source: str, target: str) -> bool:
        if source == target:
            return True
        if source == "*/*" or target == "*/*":
            return True
        if source.endswith("/*"):
            return target.startswith(source[:-1])
        if target.endswith("/*"):
            return source.startswith(target[:-1])
        return False

    def validate_workflow(self, nodes: list[dict], edges: list[dict]) -> tuple[bool, str | None]:
        """
        验证工作流的有效性。

        Args:
            nodes: List of node dictionaries with 'id' and 'type' keys
            edges: List of edge dictionaries with 'source' and 'target' keys

        Returns:
            (is_valid, error_message)
        """
        # 1. 验证节点类型存在
        for node in nodes:
            node_type = node.get("type")
            if not isinstance(node_type, str):
                return False, f"Unknown node type: {node_type}"
            if not self._node_registry.get_node_definition(node_type):
                return False, f"Unknown node type: {node_type}"

        return True, None
