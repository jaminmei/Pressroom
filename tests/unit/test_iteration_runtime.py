from __future__ import annotations

import asyncio

import pytest

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.dag_scheduler import DAGNode, NodeExecutionContext
from app.services.iteration_runtime import (
    ITERATION_ITEM_LIMIT,
    ITERATION_RESULT_OUTPUT_LIMIT_BYTES,
    build_iteration_runtime_input,
    extract_iteration_items,
    make_iteration_node_executor,
    parse_iteration_runtime_config,
)


def _workflow(
    inner_type: str = "engine/ocr", inner_config: dict[str, object] | None = None
) -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="iter_1",
                type="processor/iteration",
                config={
                    "engine_node_type": inner_type,
                    "engine_config": inner_config or {},
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


def _context(completed_outputs: dict[str, NodeOutput] | None = None) -> NodeExecutionContext:
    return NodeExecutionContext(run_id="run-1", completed_outputs=completed_outputs or {})


def _iteration_node(**config_overrides: object) -> DAGNode:
    config: dict[str, object] = {
        "engine_node_type": "engine/ocr",
        "engine_config": {},
        "iterate_over": "binary",
        "item_input_port": "image",
        "mode": "sequential",
        "max_concurrency": 5,
        "error_handling": "terminate",
    }
    config.update(config_overrides)
    return DAGNode(node_id="iter_1", node_type="processor/iteration", config=config)


def test_parse_iteration_runtime_config_applies_locked_defaults_and_rejects_bool_concurrency() -> (
    None
):
    parsed = parse_iteration_runtime_config({"engine_node_type": "engine/ocr"})

    assert parsed.engine_node_type == "engine/ocr"
    assert parsed.engine_config == {}
    assert parsed.iterate_over == "binary"
    assert parsed.item_input_port == "image"
    assert parsed.mode == "sequential"
    assert parsed.max_concurrency == 5
    assert parsed.error_handling == "terminate"

    with pytest.raises(EngineError) as exc_info:
        parse_iteration_runtime_config({"engine_node_type": "engine/ocr", "max_concurrency": True})

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG


def test_parse_iteration_runtime_config_rejects_nested_iteration() -> None:
    with pytest.raises(EngineError) as exc_info:
        parse_iteration_runtime_config({"engine_node_type": "processor/iteration"})

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG


def test_extract_iteration_items_handles_binary_and_strict_structured_elements() -> None:
    binary_items = extract_iteration_items(
        NodeOutput(binary=[BinaryRef(data="a"), BinaryRef(data="b")]),
        "binary",
    )
    assert len(binary_items) == 2

    structured_items = extract_iteration_items(
        NodeOutput(structured={"elements": [{"kind": "first"}, {"kind": "second"}]}),
        "structured.elements",
    )
    assert structured_items == [{"kind": "first"}, {"kind": "second"}]

    assert extract_iteration_items(NodeOutput(structured=None), "structured.elements") == []

    with pytest.raises(EngineError) as exc_info:
        extract_iteration_items(
            NodeOutput(structured={"elements": {"bad": True}}), "structured.elements"
        )

    assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE


def test_build_iteration_runtime_input_preserves_binary_refs_and_wraps_scalars() -> None:
    ref_only = BinaryRef(ref="/tmp/image.png", mime_type="image/png", size_bytes=4)
    binary_input = build_iteration_runtime_input(ref_only, iterate_over="binary", port_name="image")

    assert binary_input["image"].text is None
    assert binary_input["image"].binary == [ref_only]

    structured_input = build_iteration_runtime_input(
        "hello",
        iterate_over="structured.elements",
        port_name="input",
    )
    assert structured_input["input"].structured == {"value": "hello"}


@pytest.mark.asyncio()
async def test_iteration_executor_returns_empty_result_for_empty_iterable() -> None:
    calls: list[str] = []

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        calls.append(node.node_id)
        _ = (inputs, context)
        return NodeOutput(text="base")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    result = await executor(
        _iteration_node(iterate_over="structured.elements"),
        {"input": NodeOutput(structured=None)},
        _context({"input_1": NodeOutput(text="upstream")}),
    )

    assert calls == []
    assert result.structured == {
        "kind": "iteration_result",
        "items": [],
        "total": 0,
        "success_count": 0,
        "error_count": 0,
    }
    assert result.metadata["iteration_count"] == 0


@pytest.mark.asyncio()
async def test_iteration_executor_rejects_item_limit_before_spawning() -> None:
    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("executor should not run")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            _iteration_node(),
            {
                "input": NodeOutput(
                    binary=[BinaryRef(data=str(index)) for index in range(ITERATION_ITEM_LIMIT + 1)]
                )
            },
            _context(),
        )

    assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE


@pytest.mark.asyncio()
async def test_iteration_executor_continue_and_remove_failed_aggregate_deterministically() -> None:
    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (inputs, context)
        if node.node_id.endswith("__item_1"):
            raise RuntimeError("secret provider response")
        return NodeOutput(text=f"ok-{node.node_id[-1]}")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    continue_result = await executor(
        _iteration_node(error_handling="continue"),
        {
            "input": NodeOutput(
                binary=[BinaryRef(data="a"), BinaryRef(data="b"), BinaryRef(data="c")]
            )
        },
        _context(),
    )

    assert continue_result.structured is not None
    assert continue_result.structured["items"][0]["status"] == "success"
    assert continue_result.structured["items"][1]["status"] == "error"
    assert continue_result.structured["items"][1]["error"] == "Iteration item failed"
    assert continue_result.structured["total"] == 3
    assert continue_result.structured["success_count"] == 2
    assert continue_result.structured["error_count"] == 1

    remove_failed_result = await executor(
        _iteration_node(error_handling="remove_failed"),
        {
            "input": NodeOutput(
                binary=[BinaryRef(data="a"), BinaryRef(data="b"), BinaryRef(data="c")]
            )
        },
        _context(),
    )

    assert remove_failed_result.structured is not None
    assert len(remove_failed_result.structured["items"]) == 2
    assert remove_failed_result.structured["total"] == 2
    assert remove_failed_result.structured["success_count"] == 2
    assert remove_failed_result.structured["error_count"] == 0
    assert remove_failed_result.metadata["iteration_count"] == 3


@pytest.mark.asyncio()
async def test_iteration_executor_parallel_preserves_order_and_bounds_concurrency() -> None:
    active = 0
    max_active = 0

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        nonlocal active, max_active
        _ = (inputs, context)
        index = int(node.node_id.rsplit("_", 1)[-1])
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03 if index == 0 else 0.01)
        active -= 1
        return NodeOutput(text=f"done-{index}")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    result = await executor(
        _iteration_node(mode="parallel", max_concurrency=2),
        {
            "input": NodeOutput(
                binary=[BinaryRef(data="0"), BinaryRef(data="1"), BinaryRef(data="2")]
            )
        },
        _context(),
    )

    assert max_active <= 2
    assert result.structured is not None
    assert [item["index"] for item in result.structured["items"]] == [0, 1, 2]
    assert [item["output"]["text"] for item in result.structured["items"]] == [
        "done-0",
        "done-1",
        "done-2",
    ]


@pytest.mark.asyncio()
async def test_iteration_executor_parallel_terminate_fail_fast_stops_future_launches() -> None:
    started: list[int] = []
    release = asyncio.Event()

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (inputs, context)
        index = int(node.node_id.rsplit("_", 1)[-1])
        started.append(index)
        if index == 1:
            raise EngineError(
                ErrorCode.ENGINE_TIMEOUT,
                "item timeout",
                engine_name="engine/ocr",
            )
        await release.wait()
        return NodeOutput(text=f"ok-{index}")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    task = asyncio.create_task(
        executor(
            _iteration_node(mode="parallel", max_concurrency=2, error_handling="terminate"),
            {
                "input": NodeOutput(
                    binary=[
                        BinaryRef(data="0"),
                        BinaryRef(data="1"),
                        BinaryRef(data="2"),
                        BinaryRef(data="3"),
                    ]
                )
            },
            _context(),
        )
    )
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(EngineError) as exc_info:
        await task

    assert exc_info.value.error_code == ErrorCode.ENGINE_TIMEOUT
    assert started[:2] == [0, 1]
    assert 2 not in started and 3 not in started


@pytest.mark.asyncio()
@pytest.mark.parametrize("attempt", range(10))
async def test_iteration_executor_parallel_terminate_selects_lowest_failure_index_in_same_batch(
    attempt: int,
) -> None:
    _ = attempt
    started: list[int] = []
    finished: list[int] = []
    release = asyncio.Event()
    launch_log: list[int] = []

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (inputs, context)
        index = int(node.node_id.rsplit("_", 1)[-1])
        launch_log.append(index)
        started.append(index)
        await release.wait()
        finished.append(index)
        if index in {0, 1}:
            raise EngineError(
                ErrorCode.ENGINE_TIMEOUT,
                f"item timeout {index}",
                engine_name="engine/ocr",
            )
        return NodeOutput(text=f"ok-{index}")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    current_task = asyncio.current_task()
    before_tasks = set(asyncio.all_tasks())

    task = asyncio.create_task(
        executor(
            _iteration_node(mode="parallel", max_concurrency=2, error_handling="terminate"),
            {
                "input": NodeOutput(
                    binary=[
                        BinaryRef(data="0"),
                        BinaryRef(data="1"),
                        BinaryRef(data="2"),
                        BinaryRef(data="3"),
                    ]
                )
            },
            _context(),
        )
    )
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(EngineError) as exc_info:
        await task

    after_tasks = {
        item
        for item in asyncio.all_tasks()
        if item is not current_task and item not in before_tasks and not item.done()
    }

    assert exc_info.value.error_code == ErrorCode.ENGINE_TIMEOUT
    assert exc_info.value.message == "item timeout 0"
    assert launch_log == [0, 1]
    assert started == [0, 1]
    assert finished == [0, 1]
    assert not after_tasks


@pytest.mark.asyncio()
async def test_iteration_executor_raises_task_cancelled_after_cooperative_cancellation() -> None:
    launched: list[int] = []
    cancel_checks = {"count": 0}
    release = asyncio.Event()

    def _cancel_check() -> bool:
        cancel_checks["count"] += 1
        return cancel_checks["count"] >= 2

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (inputs, context)
        launched.append(int(node.node_id.rsplit("_", 1)[-1]))
        await release.wait()
        return NodeOutput(text="ok")

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
        cancel_check=_cancel_check,
    )

    task = asyncio.create_task(
        executor(
            _iteration_node(mode="parallel", max_concurrency=2, error_handling="continue"),
            {
                "input": NodeOutput(
                    binary=[BinaryRef(data="0"), BinaryRef(data="1"), BinaryRef(data="2")]
                )
            },
            _context(),
        )
    )
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(EngineError) as exc_info:
        await task

    assert exc_info.value.error_code == ErrorCode.TASK_CANCELLED
    assert launched == [0]


@pytest.mark.asyncio()
async def test_iteration_executor_enforces_compact_json_output_limit() -> None:
    oversized_text = "x" * (ITERATION_RESULT_OUTPUT_LIMIT_BYTES // 2 + 1024)

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        return NodeOutput(text=oversized_text)

    executor = make_iteration_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            _iteration_node(error_handling="continue"),
            {"input": NodeOutput(binary=[BinaryRef(data="a"), BinaryRef(data="b")])},
            _context(),
        )

    assert exc_info.value.error_code == ErrorCode.ENGINE_INVALID_RESPONSE
