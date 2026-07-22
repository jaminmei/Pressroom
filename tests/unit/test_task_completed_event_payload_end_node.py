from __future__ import annotations

from datetime import datetime, timezone

from app.api.task_helpers import task_completed_event_payload
from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskProgress,
    TaskStatus,
    WorkflowExecutionPlan,
)
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.task_orchestrator import TaskOrchestrator


def test_task_completed_event_payload_includes_output_totals_and_end_summary() -> None:
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
        ],
    )
    now = datetime.now(timezone.utc)
    context = TaskContext(
        task_id="task-end-summary",
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
            ),
            "end_1": NodeState(
                node_id="end_1",
                node_type="end/final",
                status=NodeStatus.COMPLETED,
            ),
        },
        execution_plan=WorkflowExecutionPlan(
            total_nodes=4,
            execution_order=[["input_1"], ["engine_1"], ["output_1"], ["end_1"]],
            parallel_groups=0,
        ),
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        progress=TaskProgress(
            total_nodes=4,
            completed_nodes=4,
            failed_nodes=0,
            pending_nodes=0,
            skipped_nodes=0,
            percentage=100,
        ),
        end_summary={
            "node_id": "end_1",
            "status": "completed",
            "available_result_ids": ["res_001"],
            "failed_outputs": [],
            "totals": {"outputs": 1, "available": 1, "failed_or_skipped": 0},
        },
    )

    payload = task_completed_event_payload(context)

    assert payload["summary"]["output_totals"] == {
        "total": 1,
        "completed": 1,
        "failed_or_skipped": 0,
    }
    assert payload["summary"]["end_node"]["node_id"] == "end_1"


def test_build_end_summary_includes_structured_failed_output_reasons() -> None:
    """New architecture: engine nodes connect directly to a single end/final node.

    Layout:
        input_1 → engine_ok   ──→ end_1
        input_1 → engine_fail ──→ end_1
        input_1 → engine_skip ──→ end_1
    """
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_ok", type="engine/text", config={}),
            WorkflowNode(id="engine_fail", type="engine/ocr", config={}),
            WorkflowNode(id="engine_skip", type="engine/vlm", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_ok"),
            WorkflowConnection(source="input_1", target="engine_fail"),
            WorkflowConnection(source="input_1", target="engine_skip"),
            WorkflowConnection(source="engine_ok", target="end_1"),
            WorkflowConnection(source="engine_fail", target="end_1"),
            WorkflowConnection(source="engine_skip", target="end_1"),
        ],
    )
    now = datetime.now(timezone.utc)
    context = TaskContext(
        task_id="task-end-summary-failures",
        workflow=workflow,
        status=TaskStatus.PARTIAL_COMPLETED,
        node_states={
            "input_1": NodeState(
                node_id="input_1",
                node_type="input/text",
                status=NodeStatus.COMPLETED,
            ),
            "engine_ok": NodeState(
                node_id="engine_ok",
                node_type="engine/text",
                status=NodeStatus.COMPLETED,
            ),
            "engine_fail": NodeState(
                node_id="engine_fail",
                node_type="engine/ocr",
                status=NodeStatus.FAILED,
            ),
            "engine_skip": NodeState(
                node_id="engine_skip",
                node_type="engine/vlm",
                status=NodeStatus.SKIPPED,
            ),
            "end_1": NodeState(
                node_id="end_1",
                node_type="end/final",
                status=NodeStatus.COMPLETED,
            ),
        },
        execution_plan=WorkflowExecutionPlan(
            total_nodes=5,
            execution_order=[
                ["input_1"],
                ["engine_ok", "engine_fail", "engine_skip"],
                ["end_1"],
            ],
            parallel_groups=0,
        ),
        output_result_ids={"engine_ok": "res_001"},
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        progress=TaskProgress(
            total_nodes=5,
            completed_nodes=3,
            failed_nodes=1,
            pending_nodes=0,
            skipped_nodes=1,
            percentage=100,
        ),
    )
    context.node_states["engine_fail"].error = {
        "error_code": "ENGINE_TIMEOUT",
        "message": "OCR engine timed out after 60 seconds",
    }
    context.node_states["engine_skip"].error = {
        "error_code": "NODE_DEPENDENCY_FAILED",
        "message": "前置節點 engine_fail 失敗（ENGINE_TIMEOUT），節點已跳過",
    }

    orchestrator = TaskOrchestrator.__new__(TaskOrchestrator)
    summary = orchestrator._build_end_summary(context)

    assert summary == {
        "node_id": "end_1",
        "status": "partial_completed",
        "available_result_ids": ["res_001"],
        "failed_outputs": [
            {
                "node_id": "engine_fail",
                "status": "failed",
                "error_code": "ENGINE_TIMEOUT",
                "message": "OCR engine timed out after 60 seconds",
            },
            {
                "node_id": "engine_skip",
                "status": "skipped",
                "error_code": "NODE_DEPENDENCY_FAILED",
                "message": "前置節點 engine_fail 失敗（ENGINE_TIMEOUT），節點已跳過",
            },
        ],
        "totals": {"outputs": 3, "available": 1, "failed_or_skipped": 2},
    }
