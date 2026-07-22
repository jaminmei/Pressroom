from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.errors import ErrorCode
from app.models.task import (
    NodeFailureInfo,
    NodeState,
    NodeStatus,
    TaskContext,
    build_node_failure_info,
)
from app.services.task_runner_base import TaskRunnerBase
from app.services.topological_sort import ExecutionPlan

logger = logging.getLogger(__name__)

EventPublisher = Callable[[str, TaskContext, dict[str, object]], Awaitable[None]]


class SerialTaskRunner(TaskRunnerBase):
    """Compatibility runner used only when DAG components are unavailable.

    Public workflow execution requires ``DAGScheduler`` and ``EngineClient``;
    this class retains dependency-failure helpers for legacy call sites.
    """

    def __init__(
        self,
        event_publisher: EventPublisher,
    ) -> None:
        self._publish_event = event_publisher

    async def run(self, plan: ExecutionPlan, context: TaskContext) -> None:
        raise NotImplementedError(
            "Serial workflow execution requires DAGScheduler and EngineClient."
        )

    async def cancel(self, task_id: str) -> bool:
        # Cancellation is still orchestrator-managed.
        return False

    async def execute_node(self, node_id: str, context: TaskContext) -> None:
        raise NotImplementedError("Node execution requires DAGScheduler and EngineClient.")

    def _get_predecessors(self, context: TaskContext, node_id: str) -> list[str]:
        predecessors: list[str] = []
        for connection in context.workflow.connections:
            if connection.target == node_id:
                predecessors.append(connection.source)
        return predecessors

    def _build_dependency_failure(self, predecessor: NodeState) -> NodeFailureInfo:
        dependency_error_code = None
        if isinstance(predecessor.error, dict):
            upstream_error_code = predecessor.error.get("error_code")
            if isinstance(upstream_error_code, str) and upstream_error_code:
                dependency_error_code = upstream_error_code

        if predecessor.status == NodeStatus.FAILED:
            if dependency_error_code:
                message = (
                    f"前置節點 {predecessor.node_id} 失敗（{dependency_error_code}），節點已跳過"
                )
            else:
                message = f"前置節點 {predecessor.node_id} 失敗，節點已跳過"
        else:
            message = f"前置節點 {predecessor.node_id} 已跳過，節點已跳過"

        details: dict[str, object] = {
            "dependency_node_id": predecessor.node_id,
            "dependency_status": predecessor.status.value,
        }
        if dependency_error_code:
            details["dependency_error_code"] = dependency_error_code

        return build_node_failure_info(
            error_code=ErrorCode.NODE_DEPENDENCY_FAILED.value,
            message=message,
            details=details,
        )

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
