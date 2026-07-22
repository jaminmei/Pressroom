from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskProgress,
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
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


def _context(
    *,
    task_id: str,
    status: TaskStatus,
    workflow_id: str,
    created_at: datetime,
    started_at: datetime | None,
    completed_at: datetime | None,
    duration_ms: int | None,
    node_statuses: list[NodeStatus],
) -> TaskContext:
    node_states = {
        f"node_{index}": NodeState(
            node_id=f"node_{index}",
            node_type="engine/text",
            status=node_status,
        )
        for index, node_status in enumerate(node_statuses, start=1)
    }
    progress = TaskProgress(
        total_nodes=len(node_states),
        completed_nodes=sum(1 for item in node_statuses if item == NodeStatus.COMPLETED),
        failed_nodes=sum(1 for item in node_statuses if item == NodeStatus.FAILED),
        pending_nodes=sum(1 for item in node_statuses if item == NodeStatus.PENDING),
        skipped_nodes=sum(1 for item in node_statuses if item == NodeStatus.SKIPPED),
        percentage=100 if status == TaskStatus.COMPLETED else 50,
    )
    return TaskContext(
        task_id=task_id,
        workflow=_workflow(),
        workflow_id=workflow_id,
        workflow_name=f"wf-{workflow_id}",
        status=status,
        node_states=node_states,
        execution_plan=WorkflowExecutionPlan(
            total_nodes=3,
            execution_order=[["input_1"], ["engine_1"], ["output_1"]],
            parallel_groups=3,
        ),
        created_at=created_at,
        updated_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        progress=progress,
    )


def test_task_history_service_filters_paginates_and_uses_duration_fallback() -> None:
    now = datetime.now(timezone.utc)
    completed_with_fallback = _context(
        task_id="task-history-001",
        status=TaskStatus.COMPLETED,
        workflow_id="wf-step13",
        created_at=now,
        started_at=now - timedelta(seconds=2),
        completed_at=now,
        duration_ms=None,
        node_statuses=[NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED],
    )
    running = _context(
        task_id="task-history-002",
        status=TaskStatus.RUNNING,
        workflow_id="wf-other",
        created_at=now - timedelta(minutes=1),
        started_at=now - timedelta(minutes=1),
        completed_at=None,
        duration_ms=None,
        node_statuses=[NodeStatus.RUNNING, NodeStatus.PENDING],
    )

    service = TaskHistoryService()
    items, total = service.list_history(
        {
            completed_with_fallback.task_id: completed_with_fallback,
            running.task_id: running,
        },
        page=1,
        limit=1,
        status=" completed ",
        workflow_id="wf-step13",
    )

    assert total == 1
    assert len(items) == 1
    item = items[0]
    assert item.task_id == "task-history-001"
    assert item.duration_ms == 2000
    assert item.node_summary == {"total": 3, "completed": 1, "failed": 2}


def test_task_history_service_normalizes_invalid_page_and_limit() -> None:
    now = datetime.now(timezone.utc)
    context = _context(
        task_id="task-history-003",
        status=TaskStatus.PENDING,
        workflow_id="wf-step13",
        created_at=now,
        started_at=None,
        completed_at=None,
        duration_ms=None,
        node_statuses=[NodeStatus.PENDING],
    )

    service = TaskHistoryService()
    items, total = service.list_history({context.task_id: context}, page=0, limit=0, status="all")

    assert total == 1
    assert len(items) == 1
    assert items[0].task_id == "task-history-003"
