from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.task import NodeState, TaskContext, TaskInputFile, WorkflowExecutionPlan
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.queue_task_runner import QueueTaskRunner
from app.services.topological_sort import ExecutionPlan
from app.worker_tasks import EXECUTE_WORKFLOW_TASK_NAME


class _CeleryStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_task(self, name: str, args: list[object], task_id: str | None = None) -> None:
        self.calls.append({"name": name, "args": args, "task_id": task_id})


def _build_context(tmp_path: Path) -> TaskContext:
    input_path = tmp_path / "queue_input.txt"
    input_path.write_text("hello queue", encoding="utf-8")

    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={"temperature": 0}),
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )

    now = datetime.now(timezone.utc)
    return TaskContext(
        task_id="task_queue_runner",
        workflow=workflow,
        node_states={
            "input_1": NodeState(node_id="input_1", node_type="input/text"),
            "engine_1": NodeState(node_id="engine_1", node_type="engine/text"),
            "output_1": NodeState(node_id="output_1", node_type="end/final"),
        },
        execution_plan=WorkflowExecutionPlan(
            total_nodes=3,
            execution_order=[["input_1"], ["engine_1"], ["output_1"]],
            parallel_groups=3,
            estimated_duration_seconds=1,
        ),
        input_files={
            "input_1": TaskInputFile(
                file_path=str(input_path),
                filename=input_path.name,
                mime_type="text/plain",
                size_bytes=input_path.stat().st_size,
            )
        },
        output_result_ids={"output_1": "res_001"},
        created_at=now,
        updated_at=now,
        workflow_id="wf_queue",
        workspace_id="ws_queue",
        workflow_name="Queue Workflow",
        run_name="Queue Run",
        source="evaluation",
        evaluation_run_id="eval_run_queue",
        output_format="markdown",
        engine="text",
    )


@pytest.mark.asyncio
async def test_queue_task_runner_dispatches_execute_workflow_task(tmp_path: Path) -> None:
    celery_stub = _CeleryStub()
    runner = QueueTaskRunner(celery_stub)  # type: ignore[arg-type]
    context = _build_context(tmp_path)
    plan = ExecutionPlan(
        total_nodes=3,
        execution_order=[["input_1"], ["engine_1"], ["output_1"]],
        parallel_groups=3,
        estimated_duration_seconds=1,
    )

    await runner.run(plan, context)

    assert len(celery_stub.calls) == 1
    dispatched = celery_stub.calls[0]
    assert dispatched["name"] == EXECUTE_WORKFLOW_TASK_NAME
    assert dispatched["task_id"] == context.task_id
    args = dispatched["args"]
    assert isinstance(args, list)
    assert args[0] == context.task_id
    assert args[1] == context.workflow.model_dump(mode="json")
    assert args[2] == {
        "input_1": {
            **context.input_files["input_1"].model_dump(mode="json"),
            "workspace_id": "ws_queue",
        },
    }
    assert args[3] == {
        "workflow_id": "wf_queue",
        "workflow_name": "Queue Workflow",
        "run_name": "Queue Run",
        "source": "evaluation",
        "evaluation_run_id": "eval_run_queue",
        "workspace_id": "ws_queue",
        "requested_by_user_id": None,
    }


@pytest.mark.asyncio
async def test_queue_task_runner_rejects_missing_workspace_scope(tmp_path: Path) -> None:
    celery_stub = _CeleryStub()
    runner = QueueTaskRunner(celery_stub)  # type: ignore[arg-type]
    context = _build_context(tmp_path).model_copy(update={"workspace_id": None})

    with pytest.raises(ValueError, match="workspace scope"):
        await runner.run(
            ExecutionPlan(
                total_nodes=3,
                execution_order=[["input_1"], ["engine_1"], ["output_1"]],
                parallel_groups=3,
                estimated_duration_seconds=1,
            ),
            context,
        )


@pytest.mark.asyncio
async def test_queue_task_runner_rejects_cross_workspace_binding(tmp_path: Path) -> None:
    celery_stub = _CeleryStub()
    runner = QueueTaskRunner(celery_stub)  # type: ignore[arg-type]
    binding = (
        _build_context(tmp_path)
        .input_files["input_1"]
        .model_copy(update={"workspace_id": "ws_other"})
    )
    context = _build_context(tmp_path).model_copy(update={"input_files": {"input_1": binding}})

    with pytest.raises(ValueError, match="workspace mismatch"):
        await runner.run(
            ExecutionPlan(
                total_nodes=3,
                execution_order=[["input_1"], ["engine_1"], ["output_1"]],
                parallel_groups=3,
                estimated_duration_seconds=1,
            ),
            context,
        )


@pytest.mark.asyncio
async def test_queue_task_runner_revokes_domain_task_id() -> None:
    class _ControlStub:
        def __init__(self) -> None:
            self.revoked: list[tuple[str, bool]] = []

        def revoke(self, task_id: str, terminate: bool) -> None:
            self.revoked.append((task_id, terminate))

    class _CeleryWithControl:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self._control = _ControlStub()

        def send_task(self, name: str, args: list[object], task_id: str | None = None) -> None:
            self.calls.append({"name": name, "args": args, "task_id": task_id})

        @property
        def control(self) -> _ControlStub:
            return self._control

    celery_stub = _CeleryWithControl()
    runner = QueueTaskRunner(celery_stub)  # type: ignore[arg-type]

    cancelled = await runner.cancel("task_any")

    assert cancelled is True
    assert celery_stub.control.revoked == [("task_any", False)]
