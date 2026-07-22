from __future__ import annotations

from dataclasses import dataclass

from app.models.task import TaskContext
from app.models.workflow import WorkflowDefinition
from app.services.task_orchestrator import TaskOrchestrator


@dataclass(frozen=True, slots=True)
class PersistedWorkflowExecution:
    file_ids: list[str]
    workflow_id: str
    workflow_name: str | None
    run_name: str | None
    workspace_id: str
    requested_by_user_id: str


class WorkflowExecutionService:
    def __init__(self, orchestrator: TaskOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(
        self,
        definition: WorkflowDefinition,
        execution: PersistedWorkflowExecution,
    ) -> TaskContext:
        return await self._orchestrator.create_from_workflow(
            definition,
            file_ids=execution.file_ids,
            workflow_id=execution.workflow_id,
            workflow_name=execution.workflow_name,
            run_name=execution.run_name,
            workspace_id=execution.workspace_id,
            requested_by_user_id=execution.requested_by_user_id,
        )
