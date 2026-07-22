from __future__ import annotations

from celery import Celery

from app.models.task import TaskContext
from app.services.task_runner_base import TaskRunnerBase
from app.services.topological_sort import ExecutionPlan
from app.worker_tasks import EXECUTE_WORKFLOW_TASK_NAME


class QueueTaskRunner(TaskRunnerBase):
    """Dispatch workflow execution to Celery workers."""

    def __init__(
        self,
        celery_app: Celery,
        *,
        task_name: str = EXECUTE_WORKFLOW_TASK_NAME,
    ) -> None:
        self._celery_app = celery_app
        self._task_name = task_name

    async def run(self, plan: ExecutionPlan, context: TaskContext) -> None:
        _ = plan  # queue mode delegates execution to worker process.
        if context.workspace_id is None:
            raise ValueError("Queue workflow requires workspace scope")

        input_data: dict[str, dict[str, object]] = {}
        for node_id, binding in context.input_files.items():
            if binding.workspace_id not in (None, context.workspace_id):
                raise ValueError(f"Input binding workspace mismatch for node: {node_id}")
            scoped_binding = binding.model_copy(update={"workspace_id": context.workspace_id})
            input_data[node_id] = scoped_binding.model_dump(mode="json")

        self._celery_app.send_task(
            self._task_name,
            args=[
                context.task_id,
                context.workflow.model_dump(mode="json"),
                input_data,
                {
                    "workflow_id": context.workflow_id,
                    "workflow_name": context.workflow_name,
                    "run_name": context.run_name,
                    "source": context.source,
                    "evaluation_run_id": context.evaluation_run_id,
                    **(
                        {
                            "workspace_id": context.workspace_id,
                            "requested_by_user_id": context.requested_by_user_id,
                        }
                        if context.workspace_id is not None
                        else {}
                    ),
                },
            ],
            task_id=context.task_id,
        )

    async def cancel(self, task_id: str) -> bool:
        self._celery_app.control.revoke(task_id, terminate=False)
        return True
