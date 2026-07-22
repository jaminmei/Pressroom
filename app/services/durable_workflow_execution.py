from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition
from app.providers.store import ProviderStore
from app.services.dag_scheduler import DAGRunResult, DAGScheduler, NodeExecutor
from app.services.engine_client import EngineClient, make_node_executor


class DurableWorkflowExecutionService:
    def __init__(
        self,
        *,
        dag_scheduler: DAGScheduler,
        engine_client: EngineClient | None,
        auth_resolver: object,
        provider_store: ProviderStore,
    ) -> None:
        self._dag_scheduler = dag_scheduler
        self._engine_client = engine_client
        self._auth_resolver = auth_resolver
        self._provider_store = provider_store

    async def execute(
        self,
        workflow: WorkflowDefinition,
        *,
        task_id: str,
        input_bindings: dict[str, TaskInputFile],
        workspace_id: str,
        cancel_check: Callable[[], bool] | None = None,
        node_executor: NodeExecutor | None = None,
    ) -> DAGRunResult:
        if node_executor is not None:
            executor = node_executor
        else:
            if self._engine_client is None:
                raise RuntimeError("Engine client is required without a node executor")
            executor = make_node_executor(
                self._engine_client,
                auth_resolver=self._auth_resolver,
                provider_resolver=lambda provider_id: self._provider_store.get_for_runtime(
                    provider_id,
                    workspace_id,
                ),
            )
        return await self._dag_scheduler.run(
            workflow,
            node_executor=executor,
            run_id=task_id,
            input_bindings=input_bindings,
            cancel_check=cancel_check,
        )


def execute_workflow_sync(
    *,
    workflow: WorkflowDefinition,
    task_id: str,
    input_bindings: dict[str, TaskInputFile],
    workspace_id: str,
    dag_scheduler: DAGScheduler,
    engine_client: EngineClient | None,
    auth_resolver: object,
    provider_store: ProviderStore,
    cancel_check: Callable[[], bool] | None = None,
    node_executor: NodeExecutor | None = None,
) -> DAGRunResult:
    return asyncio.run(
        DurableWorkflowExecutionService(
            dag_scheduler=dag_scheduler,
            engine_client=engine_client,
            auth_resolver=auth_resolver,
            provider_store=provider_store,
        ).execute(
            workflow,
            task_id=task_id,
            input_bindings=input_bindings,
            workspace_id=workspace_id,
            cancel_check=cancel_check,
            node_executor=node_executor,
        )
    )
