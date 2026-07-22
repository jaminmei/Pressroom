from __future__ import annotations

from collections.abc import Mapping

from app.models.task import NodeStatus, TaskContext, TaskHistorySummary


class TaskHistoryService:
    VALID_STATUSES = {
        "all",
        "pending",
        "running",
        "completed",
        "partial_completed",
        "failed",
        "cancelled",
    }

    def list_history(
        self,
        tasks: Mapping[str, TaskContext],
        *,
        page: int = 1,
        limit: int = 20,
        status: str = "all",
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[list[TaskHistorySummary], int]:
        safe_page = max(page, 1)
        safe_limit = max(limit, 1)

        normalized_status = status.lower().strip()
        summaries = [self._build_summary(context) for context in tasks.values()]
        summaries.sort(key=lambda item: item.created_at, reverse=True)

        if normalized_status != "all":
            summaries = [item for item in summaries if item.status == normalized_status]

        if workflow_id:
            summaries = [item for item in summaries if item.workflow_id == workflow_id]

        if workspace_id:
            summaries = [item for item in summaries if item.workspace_id == workspace_id]

        total = len(summaries)
        start = (safe_page - 1) * safe_limit
        end = start + safe_limit
        return summaries[start:end], total

    def _build_summary(self, context: TaskContext) -> TaskHistorySummary:
        node_states = list(context.node_states.values())
        total = len(node_states)
        completed = sum(1 for node in node_states if node.status == NodeStatus.COMPLETED)
        failed = sum(
            1 for node in node_states if node.status in {NodeStatus.FAILED, NodeStatus.SKIPPED}
        )

        duration_ms = context.duration_ms
        if duration_ms is None and context.started_at and context.completed_at:
            duration_ms = max(
                int((context.completed_at - context.started_at).total_seconds() * 1000),
                0,
            )

        return TaskHistorySummary(
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            workspace_id=context.workspace_id,
            workflow_name=context.workflow_name,
            status=context.status.value,
            created_at=context.created_at,
            completed_at=context.completed_at,
            duration_ms=duration_ms,
            node_summary={
                "total": total,
                "completed": completed,
                "failed": failed,
            },
        )
