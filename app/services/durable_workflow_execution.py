from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import get_settings
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition
from app.providers.store import ProviderStore
from app.services.adaptor_executor import (
    make_adaptor_node_executor,
    validate_adaptor_sandbox_broker_url,
)
from app.services.dag_scheduler import DAGRunResult, DAGScheduler, NodeExecutor
from app.services.engine_client import EngineClient, make_node_executor
from app.services.iteration_runtime import make_iteration_node_executor
from app.services.sandbox_client import SandboxClient


@dataclass
class AdaptorExecutorRuntime:
    executor: NodeExecutor
    aclose: Callable[[], Awaitable[None]]


def _workflow_has_adaptor_node(workflow: WorkflowDefinition) -> bool:
    return any(node.type == "processor/adaptor" for node in workflow.nodes)


def _workflow_has_iteration_node(workflow: WorkflowDefinition) -> bool:
    return any(node.type == "processor/iteration" for node in workflow.nodes)


def _workflow_has_iteration_inner_adaptor(workflow: WorkflowDefinition) -> bool:
    return any(
        node.type == "processor/iteration"
        and isinstance(node.config.get("engine_node_type"), str)
        and node.config.get("engine_node_type") == "processor/adaptor"
        for node in workflow.nodes
    )


def build_composite_executor_runtime(
    *,
    base_executor: NodeExecutor,
    workflow: WorkflowDefinition,
    cancel_check: Callable[[], bool] | None = None,
) -> AdaptorExecutorRuntime:
    executor = base_executor
    sandbox_client: SandboxClient | None = None

    needs_adaptor = _workflow_has_adaptor_node(workflow) or _workflow_has_iteration_inner_adaptor(
        workflow
    )
    if needs_adaptor:
        broker_url = validate_adaptor_sandbox_broker_url(get_settings().adaptor_sandbox_broker_url)
        sandbox_client = SandboxClient(base_url=broker_url)
        executor = make_adaptor_node_executor(
            base_executor=executor,
            definition_resolver=lambda _run_id: workflow,
            sandbox_client_factory=lambda: sandbox_client,
            settings_getter=get_settings,
        )

    if _workflow_has_iteration_node(workflow):
        executor = make_iteration_node_executor(
            base_executor=executor,
            definition_resolver=lambda _run_id: workflow,
            cancel_check=cancel_check,
        )

    async def _aclose() -> None:
        if sandbox_client is not None:
            await sandbox_client.close()

    return AdaptorExecutorRuntime(executor=executor, aclose=_aclose)


def build_adaptor_executor_runtime(
    *,
    base_executor: NodeExecutor,
    workflow: WorkflowDefinition,
    cancel_check: Callable[[], bool] | None = None,
) -> AdaptorExecutorRuntime:
    return build_composite_executor_runtime(
        base_executor=base_executor,
        workflow=workflow,
        cancel_check=cancel_check,
    )


class DurableWorkflowExecutionService:
    def __init__(
        self,
        *,
        dag_scheduler: DAGScheduler,
        engine_client: EngineClient | None,
        auth_resolver: object | None,
        provider_store: ProviderStore | None,
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
            base_executor = node_executor
        else:
            if self._engine_client is None:
                raise RuntimeError("Engine client is required without a node executor")
            if self._auth_resolver is None or self._provider_store is None:
                raise RuntimeError(
                    "Auth resolver and provider store are required without a node executor"
                )
            base_executor = make_node_executor(
                self._engine_client,
                auth_resolver=self._auth_resolver,
                provider_resolver=lambda provider_id: self._provider_store.get_for_runtime(
                    provider_id,
                    workspace_id,
                ),
            )
        if not (_workflow_has_adaptor_node(workflow) or _workflow_has_iteration_node(workflow)):
            return await self._dag_scheduler.run(
                workflow,
                node_executor=base_executor,
                run_id=task_id,
                input_bindings=input_bindings,
                cancel_check=cancel_check,
            )

        runtime = build_adaptor_executor_runtime(
            base_executor=base_executor,
            workflow=workflow,
            cancel_check=cancel_check,
        )
        try:
            return await self._dag_scheduler.run(
                workflow,
                node_executor=runtime.executor,
                run_id=task_id,
                input_bindings=input_bindings,
                cancel_check=cancel_check,
            )
        finally:
            await runtime.aclose()


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
