from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskStatus,
    WorkflowExecutionPlan,
)
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.task_history import TaskHistoryService


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="output/markdown", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


def _context(
    task_id: str,
    *,
    status: TaskStatus,
    created_at: datetime,
    workflow_id: str | None,
    workflow_name: str | None,
) -> TaskContext:
    node_states = {
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
            node_type="output/markdown",
            status=NodeStatus.COMPLETED if status == TaskStatus.COMPLETED else NodeStatus.FAILED,
        ),
    }

    context = TaskContext(
        task_id=task_id,
        workflow=_workflow(),
        status=status,
        node_states=node_states,
        execution_plan=WorkflowExecutionPlan(
            total_nodes=3,
            execution_order=[["input_1"], ["engine_1"], ["output_1"]],
            parallel_groups=3,
            estimated_duration_seconds=3,
        ),
        created_at=created_at,
        updated_at=created_at,
        started_at=created_at,
        completed_at=created_at + timedelta(seconds=2),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        duration_ms=2000,
    )
    context.refresh_progress()
    return context


def test_task_history_service_filters_by_status_and_workflow() -> None:
    now = datetime.now(timezone.utc)
    tasks = {
        "task_1": _context(
            "task_1",
            status=TaskStatus.COMPLETED,
            created_at=now,
            workflow_id="wf_1",
            workflow_name="WF 1",
        ),
        "task_2": _context(
            "task_2",
            status=TaskStatus.FAILED,
            created_at=now - timedelta(minutes=1),
            workflow_id="wf_2",
            workflow_name="WF 2",
        ),
    }

    items, total = TaskHistoryService().list_history(
        tasks,
        page=1,
        limit=20,
        status="completed",
        workflow_id="wf_1",
    )

    assert total == 1
    assert len(items) == 1
    assert items[0].task_id == "task_1"
    assert items[0].workflow_name == "WF 1"
    assert items[0].node_summary["total"] == 3


def test_task_history_service_paginates() -> None:
    now = datetime.now(timezone.utc)
    tasks = {
        f"task_{index}": _context(
            f"task_{index}",
            status=TaskStatus.COMPLETED,
            created_at=now - timedelta(minutes=index),
            workflow_id="wf_common",
            workflow_name="WF",
        )
        for index in range(5)
    }

    items, total = TaskHistoryService().list_history(tasks, page=2, limit=2, status="all")

    assert total == 5
    assert len(items) == 2
    assert items[0].task_id == "task_2"
