from __future__ import annotations

import asyncio
import base64
import os
import stat
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from app.config import get_settings
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import NodeOutput
from app.models.workflow import WorkflowDefinition
from app.services.adaptor_resolver import BindingResolutionError, resolve_adaptor_inputs
from app.services.dag_scheduler import DAGNode, NodeExecutionContext, NodeExecutor
from app.services.sandbox_client import SandboxClient
from app.storage.utils import ensure_path_within_root
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits

_ADAPTOR_NODE_TYPE = "processor/adaptor"
_EXPECTED_NETWORK_POLICY = "runner-network-none"
_EXPECTED_BROKER_URL = "http://adaptor-sandbox-broker:8080"
_SUPPORTED_INPUT_MODES = {"all_upstream", "custom_bindings"}


class _BrokerSettings(Protocol):
    adaptor_sandbox_broker_url: str
    storage_root: str


def _strict_code(config: dict[str, object]) -> str:
    code = config.get("code")
    if not isinstance(code, str) or not code.strip():
        raise EngineError(
            ErrorCode.INVALID_NODE_CONFIG,
            "Sandbox request is invalid",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    return code


def _input_mode(config: dict[str, object]) -> str:
    if "input_mode" not in config:
        return "all_upstream"
    raw_mode = config.get("input_mode")
    if not isinstance(raw_mode, str) or not raw_mode.strip():
        raise EngineError(
            ErrorCode.INVALID_NODE_CONFIG,
            "Sandbox request is invalid",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    normalized_mode = raw_mode.strip()
    if normalized_mode not in _SUPPORTED_INPUT_MODES:
        raise EngineError(
            ErrorCode.INVALID_NODE_CONFIG,
            "Sandbox request is invalid",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    return normalized_mode


def _input_bindings(config: dict[str, object]) -> list[dict[str, object]] | None:
    if "input_bindings" not in config:
        return None
    raw_bindings = config.get("input_bindings")
    if not isinstance(raw_bindings, list):
        raise EngineError(
            ErrorCode.INVALID_NODE_CONFIG,
            "Sandbox request is invalid",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    return raw_bindings


def validate_adaptor_sandbox_broker_url(broker_url: str) -> str:
    parsed = urlsplit(broker_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "adaptor-sandbox-broker"
        or parsed.port != 8080
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise EngineError(
            ErrorCode.ENGINE_UNREACHABLE,
            "Sandbox broker is unreachable",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    return _EXPECTED_BROKER_URL


async def assert_adaptor_sandbox_ready(client: SandboxClient) -> None:
    health = await client.health()
    if health.get("runner_reachable") is not True:
        raise EngineError(
            ErrorCode.ENGINE_UNREACHABLE,
            "Sandbox broker is unreachable",
            engine_name=_ADAPTOR_NODE_TYPE,
        )

    config = await client.config()
    if config.get("policy_digest") != POLICY_DIGEST:
        raise EngineError(
            ErrorCode.ENGINE_INVALID_RESPONSE,
            "Sandbox broker returned an invalid config response",
            engine_name=_ADAPTOR_NODE_TYPE,
        )
    if config.get("network_policy") != _EXPECTED_NETWORK_POLICY:
        raise EngineError(
            ErrorCode.ENGINE_INVALID_RESPONSE,
            "Sandbox broker returned an invalid config response",
            engine_name=_ADAPTOR_NODE_TYPE,
        )


def _read_storage_root_binary_ref(path: Path, *, max_bytes: int) -> bytes:
    try:
        with open(path, "rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("binary ref must resolve to a regular file")
            if file_stat.st_size > max_bytes:
                raise ValueError("binary ref exceeds max_binary_item_bytes")
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        raise ValueError("binary ref is unreadable") from exc

    if len(data) > max_bytes:
        raise ValueError("binary ref exceeds max_binary_item_bytes")
    if len(data) != file_stat.st_size:
        raise ValueError("binary ref changed during read")
    return data


def _inline_storage_root_binary_refs(
    inputs: dict[str, NodeOutput],
    *,
    storage_root: str,
    max_binary_item_bytes: int,
) -> dict[str, NodeOutput]:
    prepared: dict[str, NodeOutput] = {}
    storage_root_path = Path(storage_root)

    for name, output in inputs.items():
        binary: list[dict[str, object] | object] = []
        for item in output.binary:
            cloned_item = item.model_copy(deep=True)
            if cloned_item.ref:
                candidate_path = Path(cloned_item.ref)
                resolved_candidate = (
                    candidate_path
                    if candidate_path.is_absolute()
                    else storage_root_path / candidate_path
                )
                try:
                    safe_path = ensure_path_within_root(resolved_candidate, storage_root_path)
                except ValueError as exc:
                    raise EngineError(
                        ErrorCode.INVALID_NODE_CONFIG,
                        "Sandbox request is invalid",
                        engine_name=_ADAPTOR_NODE_TYPE,
                    ) from exc
                try:
                    data = _read_storage_root_binary_ref(
                        safe_path,
                        max_bytes=max_binary_item_bytes,
                    )
                except ValueError as exc:
                    raise EngineError(
                        ErrorCode.INVALID_NODE_CONFIG,
                        "Sandbox request is invalid",
                        engine_name=_ADAPTOR_NODE_TYPE,
                    ) from exc
                cloned_item.data = base64.b64encode(data).decode("ascii")
                cloned_item.ref = ""
            binary.append(cloned_item)

        prepared[name] = output.model_copy(
            update={
                "binary": binary,
                "structured": deepcopy(output.structured),
                "metadata": deepcopy(output.metadata),
            },
            deep=True,
        )

    return prepared


def make_adaptor_node_executor(
    *,
    base_executor: NodeExecutor,
    definition_resolver: Callable[[str], WorkflowDefinition],
    sandbox_client_factory: Callable[[], SandboxClient] | None = None,
    settings_getter: Callable[[], _BrokerSettings] = get_settings,
) -> NodeExecutor:
    sandbox_client: SandboxClient | None = None
    broker_settings: _BrokerSettings | None = None

    def _get_client() -> SandboxClient:
        nonlocal sandbox_client, broker_settings
        if sandbox_client is None:
            settings = settings_getter()
            broker_settings = settings
            broker_url = validate_adaptor_sandbox_broker_url(
                str(settings.adaptor_sandbox_broker_url)
            )
            if sandbox_client_factory is not None:
                sandbox_client = sandbox_client_factory()
            else:
                sandbox_client = SandboxClient(
                    base_url=broker_url,
                )
        return sandbox_client

    async def executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        if node.node_type != _ADAPTOR_NODE_TYPE:
            return await base_executor(node, inputs, context)

        if context is None:
            raise EngineError(
                ErrorCode.INVALID_NODE_CONFIG,
                "Sandbox request is invalid",
                engine_name=_ADAPTOR_NODE_TYPE,
            )

        code = _strict_code(node.config)

        try:
            resolved_inputs = resolve_adaptor_inputs(
                definition=definition_resolver(context.run_id),
                target_node_id=node.node_id,
                target_parent_node_id=context.target_parent_node_id,
                completed_outputs=context.completed_outputs,
                input_mode=_input_mode(node.config),
                bindings=_input_bindings(node.config),
                trusted_scope=context.trusted_iteration_scope,
            )
        except BindingResolutionError as exc:
            raise EngineError(
                ErrorCode.INVALID_NODE_CONFIG,
                str(exc),
                engine_name=_ADAPTOR_NODE_TYPE,
            ) from exc

        client = _get_client()
        assert broker_settings is not None
        try:
            prepared_inputs = await asyncio.to_thread(
                _inline_storage_root_binary_refs,
                resolved_inputs,
                storage_root=str(broker_settings.storage_root),
                max_binary_item_bytes=SandboxLimits().max_binary_item_bytes,
            )
        except EngineError:
            raise
        await assert_adaptor_sandbox_ready(client)
        started = time.perf_counter()
        output = await client.process(
            request_id=f"{context.run_id}:{node.node_id}",
            code=code,
            inputs=prepared_inputs,
        )
        duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
        metadata = dict(output.metadata)
        metadata.setdefault("processing_time_ms", duration_ms)
        validated = NodeOutput.model_validate(
            {
                "text": output.text,
                "binary": [item.model_dump(mode="json") for item in output.binary],
                "structured": output.structured,
                "metadata": metadata,
            }
        )
        return validated

    return executor
