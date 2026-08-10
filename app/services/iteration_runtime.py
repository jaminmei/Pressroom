from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowDefinition
from app.services.dag_scheduler import DAGNode, NodeExecutionContext, NodeExecutor
from app.services.iteration_scope import TrustedIterationScope
from app.services.node_registry import NodeRegistryService

ITERATION_ITEM_LIMIT = 100
ITERATION_RESULT_OUTPUT_LIMIT_BYTES = 5 * 1024 * 1024
_ITERATION_NODE_TYPE = "processor/iteration"
_ITERATE_OVER_VALUES = {"binary", "structured.elements"}
_MODE_VALUES = {"sequential", "parallel"}
_ERROR_HANDLING_VALUES = {"terminate", "continue", "remove_failed"}
_NODE_REGISTRY = NodeRegistryService()


@dataclass(frozen=True)
class IterationRuntimeConfig:
    engine_node_type: str
    engine_config: dict[str, object]
    iterate_over: str
    item_input_port: str
    mode: str
    max_concurrency: int
    error_handling: str


def _invalid_config() -> EngineError:
    return EngineError(
        ErrorCode.INVALID_NODE_CONFIG,
        "Iteration node config is invalid",
        engine_name=_ITERATION_NODE_TYPE,
    )


def _invalid_response() -> EngineError:
    return EngineError(
        ErrorCode.ENGINE_INVALID_RESPONSE,
        "Iteration node produced an invalid response",
        engine_name=_ITERATION_NODE_TYPE,
    )


def _compact_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _ensure_result_size(payload: object) -> None:
    if len(_compact_json_bytes(payload)) > ITERATION_RESULT_OUTPUT_LIMIT_BYTES:
        raise _invalid_response()


def parse_iteration_runtime_config(config: dict[str, object]) -> IterationRuntimeConfig:
    engine_node_type = config.get("engine_node_type", "")
    if not isinstance(engine_node_type, str) or not engine_node_type.strip():
        raise _invalid_config()
    engine_node_type = engine_node_type.strip()
    if engine_node_type == _ITERATION_NODE_TYPE:
        raise _invalid_config()
    inner_node_def = _NODE_REGISTRY.get_node_definition(engine_node_type)
    if inner_node_def is None:
        raise _invalid_config()

    engine_config = config.get("engine_config", {})
    if not isinstance(engine_config, dict):
        raise _invalid_config()

    iterate_over = config.get("iterate_over", "binary")
    if not isinstance(iterate_over, str) or iterate_over not in _ITERATE_OVER_VALUES:
        raise _invalid_config()

    item_input_port = config.get("item_input_port", "image")
    if not isinstance(item_input_port, str) or not item_input_port.strip():
        raise _invalid_config()

    mode = config.get("mode", "sequential")
    if not isinstance(mode, str) or mode not in _MODE_VALUES:
        raise _invalid_config()

    max_concurrency = config.get("max_concurrency", 5)
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
        raise _invalid_config()
    if not 1 <= max_concurrency <= 10:
        raise _invalid_config()

    error_handling = config.get("error_handling", "terminate")
    if not isinstance(error_handling, str) or error_handling not in _ERROR_HANDLING_VALUES:
        raise _invalid_config()

    return IterationRuntimeConfig(
        engine_node_type=engine_node_type,
        engine_config=dict(engine_config),
        iterate_over=iterate_over,
        item_input_port=item_input_port.strip(),
        mode=mode,
        max_concurrency=max_concurrency,
        error_handling=error_handling,
    )


def extract_iteration_items(output: NodeOutput, iterate_over: str) -> list[Any]:
    if iterate_over == "binary":
        return list(output.binary)
    if iterate_over == "structured.elements":
        if output.structured is None:
            return []
        if not isinstance(output.structured, dict):
            raise _invalid_response()
        elements = output.structured.get("elements", [])
        if not isinstance(elements, list):
            raise _invalid_response()
        return list(elements)
    raise _invalid_config()


def build_iteration_runtime_input(
    item: Any,
    *,
    iterate_over: str,
    port_name: str,
) -> dict[str, NodeOutput]:
    if iterate_over == "binary":
        if isinstance(item, BinaryRef):
            return {
                port_name: NodeOutput(
                    text=item.data,
                    binary=[item.model_copy(deep=True)],
                )
            }
        raise _invalid_response()

    if iterate_over == "structured.elements":
        return {
            port_name: NodeOutput(
                structured=deepcopy(item) if isinstance(item, dict) else {"value": deepcopy(item)},
            )
        }

    raise _invalid_config()


def _safe_item_error(exc: Exception) -> str:
    if isinstance(exc, EngineError):
        return exc.message
    return "Iteration item failed"


def _node_output_dict(output: NodeOutput) -> dict[str, object]:
    return output.model_dump(mode="json")


def _success_item_entry(index: int, output: NodeOutput) -> dict[str, object]:
    return {
        "index": index,
        "status": "success",
        "error": None,
        "output": _node_output_dict(output),
    }


def _error_item_entry(index: int, message: str) -> dict[str, object]:
    return {
        "index": index,
        "status": "error",
        "error": message,
        "output": None,
    }


def _final_output(
    *,
    config: IterationRuntimeConfig,
    attempted_count: int,
    items: list[dict[str, object]],
    success_count: int,
    error_count: int,
) -> NodeOutput:
    structured = {
        "kind": "iteration_result",
        "items": items,
        "total": len(items),
        "success_count": success_count,
        "error_count": error_count,
    }
    _ensure_result_size(structured)
    return NodeOutput(
        structured=structured,
        metadata={
            "iteration_count": attempted_count,
            "engine": config.engine_node_type,
            "mode": config.mode,
            "error_handling": config.error_handling,
        },
    )


async def _run_single_iteration_item(
    *,
    parent_node: DAGNode,
    item_index: int,
    item: Any,
    config: IterationRuntimeConfig,
    base_executor: NodeExecutor,
    context: NodeExecutionContext,
) -> NodeOutput:
    inner_node = DAGNode(
        node_id=f"{parent_node.node_id}__item_{item_index}",
        node_type=config.engine_node_type,
        config=deepcopy(config.engine_config),
    )
    inner_context = NodeExecutionContext(
        run_id=context.run_id,
        completed_outputs=context.completed_outputs,
        trusted_iteration_scope=TrustedIterationScope(
            owner_node_id=parent_node.node_id,
            item=deepcopy(item),
            index=item_index,
        )
        if config.engine_node_type == "processor/adaptor"
        else None,
        target_parent_node_id=parent_node.node_id,
    )
    return await base_executor(
        inner_node,
        build_iteration_runtime_input(
            item,
            iterate_over=config.iterate_over,
            port_name=config.item_input_port,
        ),
        inner_context,
    )


async def _execute_sequential(
    *,
    parent_node: DAGNode,
    items: list[Any],
    config: IterationRuntimeConfig,
    base_executor: NodeExecutor,
    context: NodeExecutionContext,
    cancel_check: Callable[[], bool] | None,
) -> NodeOutput:
    results: list[dict[str, object]] = []
    success_count = 0
    error_count = 0

    for index, item in enumerate(items):
        if cancel_check is not None and cancel_check():
            raise EngineError(
                ErrorCode.TASK_CANCELLED,
                "Workflow run was cancelled",
                engine_name=_ITERATION_NODE_TYPE,
            )
        try:
            output = await _run_single_iteration_item(
                parent_node=parent_node,
                item_index=index,
                item=item,
                config=config,
                base_executor=base_executor,
                context=context,
            )
        except Exception as exc:
            if config.error_handling == "terminate":
                raise exc
            if config.error_handling == "continue":
                results.append(_error_item_entry(index, _safe_item_error(exc)))
                error_count += 1
                _ensure_result_size(
                    {
                        "kind": "iteration_result",
                        "items": results,
                    }
                )
                continue
            continue

        results.append(_success_item_entry(index, output))
        success_count += 1
        _ensure_result_size(
            {
                "kind": "iteration_result",
                "items": results,
            }
        )

    return _final_output(
        config=config,
        attempted_count=len(items),
        items=results,
        success_count=success_count,
        error_count=error_count,
    )


async def _execute_parallel(
    *,
    parent_node: DAGNode,
    items: list[Any],
    config: IterationRuntimeConfig,
    base_executor: NodeExecutor,
    context: NodeExecutionContext,
    cancel_check: Callable[[], bool] | None,
) -> NodeOutput:
    results_by_index: dict[int, dict[str, object]] = {}
    success_count = 0
    error_count = 0
    running: dict[asyncio.Task[NodeOutput], int] = {}
    next_index = 0
    first_failure: Exception | None = None
    cancelled = False

    async def _launch(index: int) -> asyncio.Task[NodeOutput]:
        return asyncio.create_task(
            _run_single_iteration_item(
                parent_node=parent_node,
                item_index=index,
                item=items[index],
                config=config,
                base_executor=base_executor,
                context=context,
            )
        )

    async def _cancel_and_drain_running() -> None:
        pending_tasks = list(running.keys())
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    while next_index < len(items) or running:
        while next_index < len(items) and len(running) < config.max_concurrency and not cancelled:
            if cancel_check is not None and cancel_check():
                cancelled = True
                break
            task = await _launch(next_index)
            running[task] = next_index
            next_index += 1

        if not running:
            break

        done, _pending = await asyncio.wait(running.keys(), return_when=asyncio.FIRST_COMPLETED)
        completed_batch = sorted(
            ((running.pop(task), task) for task in done),
            key=lambda item: item[0],
        )

        batch_failure: Exception | None = None
        for index, finished in completed_batch:
            try:
                output = await finished
            except Exception as exc:
                if config.error_handling == "terminate":
                    if batch_failure is None:
                        batch_failure = exc
                    continue
                if config.error_handling == "continue":
                    results_by_index[index] = _error_item_entry(index, _safe_item_error(exc))
                    error_count += 1
                    _ensure_result_size(
                        {
                            "kind": "iteration_result",
                            "items": list(results_by_index.values()),
                        }
                    )
                    continue
                continue

            results_by_index[index] = _success_item_entry(index, output)
            success_count += 1
            _ensure_result_size(
                {
                    "kind": "iteration_result",
                    "items": list(results_by_index.values()),
                }
            )

        if batch_failure is not None:
            first_failure = batch_failure
            await _cancel_and_drain_running()

        if first_failure is not None:
            raise first_failure

    if cancelled:
        await asyncio.gather(*running.keys(), return_exceptions=True)
        raise EngineError(
            ErrorCode.TASK_CANCELLED,
            "Workflow run was cancelled",
            engine_name=_ITERATION_NODE_TYPE,
        )

    ordered_items = [results_by_index[index] for index in sorted(results_by_index)]
    return _final_output(
        config=config,
        attempted_count=len(items),
        items=ordered_items,
        success_count=success_count,
        error_count=error_count,
    )


def make_iteration_node_executor(
    *,
    base_executor: NodeExecutor,
    definition_resolver: Callable[[str], WorkflowDefinition],
    cancel_check: Callable[[], bool] | None = None,
) -> NodeExecutor:
    async def executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        if node.node_type != _ITERATION_NODE_TYPE:
            return await base_executor(node, inputs, context)

        if context is None:
            raise _invalid_config()
        _ = definition_resolver(context.run_id)
        config = parse_iteration_runtime_config(node.config)
        source_output = inputs.get("input")
        if source_output is None:
            raise _invalid_response()
        items = extract_iteration_items(source_output, config.iterate_over)
        if len(items) > ITERATION_ITEM_LIMIT:
            raise _invalid_response()

        if config.mode == "parallel":
            return await _execute_parallel(
                parent_node=node,
                items=items,
                config=config,
                base_executor=base_executor,
                context=context,
                cancel_check=cancel_check,
            )
        return await _execute_sequential(
            parent_node=node,
            items=items,
            config=config,
            base_executor=base_executor,
            context=context,
            cancel_check=cancel_check,
        )

    return executor
