from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest

from app.models.output import OutputMetadata
from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskResult,
    TaskStatus,
    WorkflowExecutionPlan,
)
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.task_run_repository import TaskRunRepository
from app.services.task_orchestrator import TaskOrchestrator


def _build_result(*, result_id: str, content: str, output_format: str = "markdown") -> TaskResult:
    return TaskResult(
        result_id=result_id,
        format=output_format,
        filename=f"{result_id}.md",
        content_type="text/markdown",
        storage_path=f"/tmp/{result_id}.md",
        download_url=f"/api/tasks/task-eval/results/{result_id}/download",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=120,
            page_count=1,
            char_count=len(content),
            word_count=max(len(content.split()), 1),
            source_filename="input.txt",
        ),
    )


def _build_context(result: TaskResult) -> TaskContext:
    now = datetime.now(timezone.utc)
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )
    return TaskContext(
        task_id="task-eval-access",
        workflow=workflow,
        status=TaskStatus.COMPLETED,
        node_states={
            "input_1": NodeState(
                node_id="input_1",
                node_type="input/text",
                status=NodeStatus.COMPLETED,
            ),
            "engine_1": NodeState(
                node_id="engine_1",
                node_type="engine/text",
                status=NodeStatus.COMPLETED,
            ),
            "output_1": NodeState(
                node_id="output_1",
                node_type="end/final",
                status=NodeStatus.COMPLETED,
                output=result,
            ),
        },
        execution_plan=WorkflowExecutionPlan(
            total_nodes=3,
            execution_order=[["input_1"], ["engine_1"], ["output_1"]],
            parallel_groups=0,
        ),
        output_result_ids={"output_1": result.result_id},
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=120,
        result=result,
    )


def test_task_context_extracts_final_output_content_and_format() -> None:
    result = _build_result(result_id="res_001", content="# Invoice\n\nTotal: 10")
    context = _build_context(result)

    content, output_format = context.extract_final_output()

    assert content == "# Invoice\n\nTotal: 10"
    assert output_format == "markdown"


def test_task_context_extract_final_output_raises_when_missing_result() -> None:
    result = _build_result(result_id="res_001", content="unused")
    context = _build_context(result)
    context.output_result_ids = {"output_1": "res_missing"}

    with pytest.raises(ValueError, match="No output result found"):
        context.extract_final_output()


@pytest.mark.asyncio
async def test_task_orchestrator_wait_for_completion_returns_terminal_context() -> None:
    result = _build_result(result_id="res_001", content="done")
    context = _build_context(result)
    completion_event = asyncio.Event()
    orchestrator = TaskOrchestrator.__new__(TaskOrchestrator)
    orchestrator._tasks = {context.task_id: context}
    orchestrator._completion_events = {context.task_id: completion_event}
    orchestrator._task_run_repository = cast(
        TaskRunRepository,
        SimpleNamespace(get_snapshot=lambda _task_id: None),
    )

    async def _complete_later() -> None:
        await asyncio.sleep(0.01)
        context.status = TaskStatus.COMPLETED
        completion_event.set()

    task = asyncio.create_task(_complete_later())
    try:
        completed = await orchestrator.wait_for_completion(context.task_id, timeout=0.1)
    finally:
        await task

    assert completed is context
    assert completion_event.is_set() is True


@pytest.mark.asyncio
async def test_task_orchestrator_wait_for_completion_times_out() -> None:
    result = _build_result(result_id="res_001", content="done")
    context = _build_context(result)
    context.status = TaskStatus.RUNNING
    orchestrator = TaskOrchestrator.__new__(TaskOrchestrator)
    orchestrator._tasks = {context.task_id: context}
    orchestrator._completion_events = {context.task_id: asyncio.Event()}
    orchestrator._task_run_repository = cast(
        TaskRunRepository,
        SimpleNamespace(get_snapshot=lambda _task_id: None),
    )

    with pytest.raises(asyncio.TimeoutError):
        await orchestrator.wait_for_completion(context.task_id, timeout=0.01)
