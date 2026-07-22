from __future__ import annotations

from datetime import datetime, timezone

from app.models.task import TaskContext, TaskStatus, WorkflowExecutionPlan
from app.models.workflow import WorkflowDefinition


def test_task_context_supports_new_workflow_fields() -> None:
    now = datetime.now(timezone.utc)

    context = TaskContext(
        task_id="task_001",
        workflow=WorkflowDefinition(nodes=[], connections=[]),
        execution_plan=WorkflowExecutionPlan(
            total_nodes=0,
            execution_order=[],
            parallel_groups=0,
            estimated_duration_seconds=0,
        ),
        created_at=now,
        updated_at=now,
        workflow_id="wf_123",
        workflow_name="Demo Workflow",
        duration_ms=1200,
    )

    assert context.status == TaskStatus.PENDING
    assert context.workflow_id == "wf_123"
    assert context.workflow_name == "Demo Workflow"
    assert context.duration_ms == 1200


def test_task_context_backward_compatible_defaults() -> None:
    now = datetime.now(timezone.utc)

    context = TaskContext(
        task_id="task_002",
        workflow=WorkflowDefinition(nodes=[], connections=[]),
        execution_plan=WorkflowExecutionPlan(
            total_nodes=0,
            execution_order=[],
            parallel_groups=0,
            estimated_duration_seconds=0,
        ),
        created_at=now,
        updated_at=now,
    )

    assert context.workflow_id is None
    assert context.workflow_name is None
    assert context.duration_ms is None
