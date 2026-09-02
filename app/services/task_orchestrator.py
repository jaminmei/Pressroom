from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from celery import Celery

from app.core.feature_flags import FeatureFlags, OrchestratorMode
from app.models.output import OutputMetadata
from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskInputFile,
    TaskResult,
    TaskStatus,
    WorkflowExecutionPlan,
    node_failure_message,
    node_failure_summary,
)
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.providers.store import ProviderStore
from app.repositories.event_log_repository import EventLogRepository
from app.repositories.node_run_repository import NodeRunRepository
from app.repositories.task_run_repository import TaskRunRepository
from app.services.dag_scheduler import DAGScheduler
from app.services.document_router import DocumentRouter
from app.services.durable_workflow_execution import DurableWorkflowExecutionService
from app.services.engine_client import EngineClient
from app.services.file_store import FileStore
from app.services.final_output_serializer import build_final_output_snapshot_entries
from app.services.node_registry import NodeRegistryService
from app.services.output_formatter.markdown_formatter import MarkdownFormatter
from app.services.queue_task_runner import QueueTaskRunner
from app.services.task_runner import SerialTaskRunner
from app.services.task_runner_base import TaskRunnerBase
from app.services.task_runner_factory import TaskRunnerFactory
from app.services.topological_sort import ExecutionPlan, build_execution_plan
from app.storage.base import StorageAdapter
from app.storage.utils import resolve_storage_path

MAX_TASKS = 1000
EVENT_QUEUE_MAXSIZE = 64
RESULT_PREVIEW_MAX_CHARS = 500
logger = logging.getLogger(__name__)


class NodeRetryError(Exception):
    """Raised when a task node cannot be retried."""

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details


class TaskOrchestrator:
    """Workflow-aware task orchestrator."""

    SUPPORTED_OUTPUT_FORMATS = {"markdown", "plaintext", "yaml", "text"}

    def __init__(
        self,
        storage: StorageAdapter,
        document_router: DocumentRouter,
        markdown_formatter: MarkdownFormatter,
        *,
        file_store: FileStore | None = None,
        event_log_repository: EventLogRepository | None = None,
        task_run_repository: TaskRunRepository | None = None,
        node_run_repository: NodeRunRepository | None = None,
        celery_app: Celery | None = None,
        dag_scheduler: DAGScheduler | None = None,
        engine_client: EngineClient | None = None,
        auth_resolver: object | None = None,
        provider_store: ProviderStore | None = None,
    ) -> None:
        self._storage = storage
        self._document_router = document_router
        self._markdown_formatter = markdown_formatter
        self._file_store = file_store or FileStore()
        self._event_log_repository = event_log_repository or EventLogRepository()
        self._task_run_repository = task_run_repository or TaskRunRepository()
        self._node_run_repository = node_run_repository or NodeRunRepository()

        self._dag_scheduler = dag_scheduler
        self._engine_client = engine_client
        self._auth_resolver = auth_resolver
        self._provider_store = provider_store
        self._runner_factory: TaskRunnerFactory | None
        self._runner: TaskRunnerBase | None

        if FeatureFlags.get_orchestrator_mode() == OrchestratorMode.QUEUE:
            self._runner_factory = TaskRunnerFactory(
                event_publisher=self._publish_event,
                celery_app=celery_app,
                node_registry=NodeRegistryService(),
            )
            self._runner = self._runner_factory.create()
        elif dag_scheduler is not None and engine_client is not None:
            self._runner = None  # DAG-based execution — no legacy runner needed
            self._runner_factory = None
        else:
            self._runner_factory = TaskRunnerFactory(
                event_publisher=self._publish_event,
                celery_app=celery_app,
                node_registry=NodeRegistryService(),
            )
            self._runner = self._runner_factory.create()

        self._tasks: dict[str, TaskContext] = {}
        self._event_queues: dict[str, asyncio.Queue[dict[str, object]]] = {}
        self._completion_events: dict[str, asyncio.Event] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._event_log_append_tails: dict[str, asyncio.Task[None]] = {}

    def _evict_completed_tasks(self) -> None:
        """Remove oldest completed tasks when store exceeds MAX_TASKS."""
        if len(self._tasks) < MAX_TASKS:
            return
        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL_COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        completed = [
            (tid, ctx) for tid, ctx in self._tasks.items() if ctx.status in terminal_statuses
        ]
        completed.sort(key=lambda x: x[1].updated_at)
        # Remove oldest quarter-batch of completed tasks
        to_remove = len(self._tasks) - MAX_TASKS + MAX_TASKS // 4
        for tid, _ in completed[:to_remove]:
            del self._tasks[tid]
            self._event_queues.pop(tid, None)
            self._completion_events.pop(tid, None)
            self._task_locks.pop(tid, None)

    async def create_and_execute(
        self,
        *,
        file_content: bytes,
        filename: str,
        mime_type: str,
        output_format: str = "markdown",
        engine: str = "ocr",
    ) -> TaskContext:
        self._evict_completed_tasks()
        task_id = f"task_{uuid4()}"
        source_path = await self._storage.save_file(task_id, "original", filename, file_content)

        definition = self._build_default_workflow(
            mime_type=mime_type, engine=engine, output_format=output_format
        )
        input_bindings = {
            "input_1": TaskInputFile(
                file_path=source_path,
                filename=filename,
                mime_type=mime_type,
                size_bytes=len(file_content),
            )
        }

        context = self._create_context(
            task_id=task_id,
            workflow=definition,
            input_files=input_bindings,
            output_format=output_format,
            engine=engine,
            source_file_path=source_path,
            source_filename=filename,
            source_mime_type=mime_type,
            workflow_id=None,
            workspace_id=None,
            workflow_name=None,
        )

        await self._publish_event(
            "task_pending",
            context,
            {
                "task_id": context.task_id,
                "status": context.status.value,
                "created_at": context.created_at.isoformat(),
            },
        )
        self._start_background(task_id)
        return context

    async def create_from_workflow(
        self,
        workflow: WorkflowDefinition,
        *,
        file_ids: list[str] | None = None,
        input_bindings: dict[str, TaskInputFile] | None = None,
        workflow_id: str | None = None,
        workflow_name: str | None = None,
        run_name: str | None = None,
        source: str = "manual",
        evaluation_run_id: str | None = None,
        workspace_id: str | None = None,
        requested_by_user_id: str | None = None,
    ) -> TaskContext:
        self._evict_completed_tasks()
        task_id = f"task_{uuid4()}"
        bindings = input_bindings or self._resolve_input_bindings(
            workflow,
            file_ids or [],
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
        )

        first_input = next(iter(bindings.values()), None)
        context = self._create_context(
            task_id=task_id,
            workflow=workflow,
            input_files=bindings,
            output_format=self._infer_output_format(workflow),
            engine=self._infer_engine(workflow),
            source_file_path=first_input.file_path if first_input else None,
            source_filename=first_input.filename if first_input else None,
            source_mime_type=first_input.mime_type if first_input else None,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            workflow_name=workflow_name,
            run_name=run_name,
            source=source,
            evaluation_run_id=evaluation_run_id,
        )

        await self._publish_event(
            "task_pending",
            context,
            {
                "task_id": context.task_id,
                "status": context.status.value,
                "created_at": context.created_at.isoformat(),
            },
        )
        self._start_background(task_id)
        return context

    def get_task(self, task_id: str, *, workspace_id: str | None = None) -> TaskContext | None:
        context = self._tasks.get(task_id)
        if context is None:
            return None
        if workspace_id is not None and context.workspace_id != workspace_id:
            return None
        return context

    def get_event_queue(
        self,
        task_id: str,
        *,
        workspace_id: str | None = None,
    ) -> asyncio.Queue[dict[str, object]] | None:
        if self.get_task(task_id, workspace_id=workspace_id) is None:
            return None
        return self._event_queues.get(task_id)

    async def wait_for_completion(
        self,
        task_id: str,
        timeout: float = 300.0,
        *,
        workspace_id: str | None = None,
    ) -> TaskContext:
        context = self.get_task(task_id, workspace_id=workspace_id)
        if context is None:
            raise KeyError(task_id)

        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL_COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        if context.status in terminal_statuses:
            return context

        event = self._completion_events.get(task_id)
        if event is None:
            event = asyncio.Event()
            self._completion_events[task_id] = event

        await asyncio.wait_for(event.wait(), timeout=timeout)

        completed = self.get_task(task_id, workspace_id=workspace_id)
        if completed is None:
            raise KeyError(task_id)
        return completed

    async def retry_node(
        self,
        task_id: str,
        node_id: str,
        *,
        workspace_id: str | None = None,
    ) -> TaskContext:
        lock = self._task_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            context = self.get_task(task_id, workspace_id=workspace_id)
            if context is None:
                raise NodeRetryError(
                    status_code=404,
                    error_code="TASK_NOT_FOUND",
                    message=f"找不到任務：{task_id}",
                )

            target_state = context.node_states.get(node_id)
            if target_state is None:
                raise NodeRetryError(
                    status_code=404,
                    error_code="NODE_NOT_FOUND",
                    message=f"找不到節點：{node_id}",
                    details={"task_id": task_id, "node_id": node_id},
                )

            effective_task_status = await self._resolve_retryable_task_status(
                context,
                workspace_id=workspace_id,
            )
            if effective_task_status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                raise NodeRetryError(
                    status_code=409,
                    error_code="TASK_ALREADY_RUNNING",
                    message=f"任務仍在執行中，目前狀態：{effective_task_status.value}",
                    details={"task_id": task_id, "current_status": effective_task_status.value},
                )

            effective_node_status = await self._resolve_retryable_node_status(
                context,
                node_id,
                workspace_id=workspace_id,
            )
            if effective_node_status != NodeStatus.FAILED:
                raise NodeRetryError(
                    status_code=409,
                    error_code="NODE_NOT_FAILED",
                    message="節點目前狀態不是 failed，無法重試",
                    details={
                        "task_id": task_id,
                        "node_id": node_id,
                        "current_status": effective_node_status.value,
                        "expected_status": "failed",
                    },
                )

            if effective_task_status == TaskStatus.CANCELLED:
                raise NodeRetryError(
                    status_code=409,
                    error_code="NODE_NOT_FAILED",
                    message=f"任務目前狀態不支援節點重試：{effective_task_status.value}",
                    details={
                        "task_id": task_id,
                        "node_id": node_id,
                        "current_status": effective_task_status.value,
                        "expected_status": "failed",
                    },
                )

            for affected_node_id in self._collect_downstream_node_ids(context.workflow, node_id):
                state = context.node_states.get(affected_node_id)
                if state is None:
                    continue
                state.status = NodeStatus.PENDING
                state.started_at = None
                state.completed_at = None
                state.output = None
                state.error = None
                state.progress = None

            context.status = TaskStatus.RUNNING
            context.started_at = None
            context.completed_at = None
            context.duration_ms = None
            context.result = None
            context.error = None
            context.cancel_requested = False
            context.updated_at = self._now()
            context.refresh_progress()
            self._sync_primary_result(context)

            await self._persist_task_run_snapshot(context, workspace_id=workspace_id)
            self._start_background(task_id)
            return context

    async def cancel_task(
        self,
        task_id: str,
        *,
        workspace_id: str | None = None,
    ) -> TaskContext | None:
        context = self.get_task(task_id, workspace_id=workspace_id)
        if context is None:
            return None

        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL_COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        if context.status in terminal_statuses:
            return context

        context.cancel_requested = True
        context.status = TaskStatus.CANCELLED
        if context.started_at and context.duration_ms is None:
            context.duration_ms = max(
                int((self._now() - context.started_at).total_seconds() * 1000),
                0,
            )
        if context.status == TaskStatus.CANCELLED:
            context.completed_at = self._now()
        context.updated_at = self._now()
        context.refresh_progress()
        await self._persist_task_run_snapshot(context, workspace_id=workspace_id)
        if self._is_queue_runner() and self._runner is not None:
            await self._runner.cancel(task_id)
        return context

    async def _resolve_retryable_task_status(
        self,
        context: TaskContext,
        *,
        workspace_id: str | None = None,
    ) -> TaskStatus:
        runtime_status = context.status
        if runtime_status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            return runtime_status

        snapshot = await self._task_run_repository.get_snapshot(
            context.task_id,
            workspace_id=workspace_id,
            expected_workspace_id=workspace_id,
        )
        snapshot_status = snapshot.status if snapshot is not None else None
        if snapshot_status not in {"failed", "partial_completed"}:
            return runtime_status

        normalized_status = TaskStatus(snapshot_status)
        context.status = normalized_status
        if snapshot is not None:
            if snapshot.completed_at is not None:
                context.completed_at = snapshot.completed_at
            if snapshot.duration_ms is not None:
                context.duration_ms = snapshot.duration_ms
            if snapshot.error is not None:
                context.error = snapshot.error
        return normalized_status

    async def _resolve_retryable_node_status(
        self,
        context: TaskContext,
        node_id: str,
        *,
        workspace_id: str | None = None,
    ) -> NodeStatus:
        state = context.node_states[node_id]
        if state.status not in {NodeStatus.PENDING, NodeStatus.RUNNING}:
            return state.status

        snapshot = await self._node_run_repository.get_snapshot(
            context.task_id,
            node_id,
            workspace_id=workspace_id,
            expected_workspace_id=workspace_id,
        )
        if snapshot is None or snapshot.status != "failed":
            return state.status

        state.status = NodeStatus.FAILED
        state.error = snapshot.error
        state.started_at = snapshot.started_at
        state.completed_at = snapshot.completed_at
        return state.status

    def _collect_downstream_node_ids(
        self,
        workflow: WorkflowDefinition,
        start_node_id: str,
    ) -> set[str]:
        pending = [start_node_id]
        visited: set[str] = set()

        while pending:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            successors = [
                connection.target
                for connection in workflow.connections
                if connection.source == current
            ]
            pending.extend(successors)

        return visited

    def _create_context(
        self,
        *,
        task_id: str,
        workflow: WorkflowDefinition,
        input_files: dict[str, TaskInputFile],
        output_format: str,
        engine: str,
        source_file_path: str | None,
        source_filename: str | None,
        source_mime_type: str | None,
        workflow_id: str | None,
        workspace_id: str | None,
        workflow_name: str | None,
        requested_by_user_id: str | None = None,
        run_name: str | None = None,
        source: str = "manual",
        evaluation_run_id: str | None = None,
    ) -> TaskContext:
        now = self._now()
        plan = build_execution_plan(workflow)

        node_states = {
            node.id: NodeState(node_id=node.id, node_type=node.type) for node in workflow.nodes
        }

        # Mark input nodes as COMPLETED since files are already bound/ready
        # They don't need to "run" in the traditional sense - the files are ready to be routed
        for node_id in input_files:
            if node_id in node_states:
                node_states[node_id].status = NodeStatus.COMPLETED

        # Build result IDs from nodes connected to end node
        end_node = next((n for n in workflow.nodes if n.type == "end/final"), None)
        upstream_of_end: list[str] = []
        if end_node is not None:
            upstream_of_end = [c.source for c in workflow.connections if c.target == end_node.id]
        output_result_ids = {
            node_id: f"res_{index:03d}" for index, node_id in enumerate(upstream_of_end, start=1)
        }

        context = TaskContext(
            task_id=task_id,
            workflow=workflow,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            workflow_name=workflow_name,
            run_name=run_name,
            source=source,
            evaluation_run_id=evaluation_run_id,
            status=TaskStatus.PENDING,
            node_states=node_states,
            execution_plan=WorkflowExecutionPlan(
                total_nodes=plan.total_nodes,
                execution_order=plan.execution_order,
                parallel_groups=plan.parallel_groups,
                estimated_duration_seconds=plan.estimated_duration_seconds,
            ),
            input_files=input_files,
            output_result_ids=output_result_ids,
            created_at=now,
            updated_at=now,
            source_file_path=source_file_path,
            source_filename=source_filename,
            source_mime_type=source_mime_type,
            output_format=output_format,
            engine=engine,
        )
        context.refresh_progress()

        self._tasks[task_id] = context
        self._event_queues[task_id] = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        self._completion_events[task_id] = asyncio.Event()
        return context

    def _start_background(self, task_id: str) -> None:
        completion_event = self._completion_events.get(task_id)
        if completion_event is not None:
            completion_event.clear()
        background_task = asyncio.create_task(self._execute(task_id))
        self._background_tasks.add(background_task)
        background_task.add_done_callback(self._background_tasks.discard)

    async def _execute(self, task_id: str) -> None:
        context = self._tasks.get(task_id)
        completion_event = self._completion_events.get(task_id)
        if context is None:
            return

        if self._is_cancel_requested(context):
            context.status = TaskStatus.CANCELLED
            context.completed_at = self._now()
            context.updated_at = self._now()
            context.duration_ms = 0
            context.refresh_progress()
            await self._publish_event(
                "task_completed",
                context,
                {
                    "task_id": context.task_id,
                    "status": context.status.value,
                    "started_at": None,
                    "completed_at": context.completed_at.isoformat(),
                    "duration_seconds": 0,
                    "summary": {
                        "total_nodes": context.progress.total_nodes,
                        "completed": context.progress.completed_nodes,
                        "failed": context.progress.failed_nodes,
                        "skipped": context.progress.skipped_nodes,
                    },
                },
            )
            await self._await_event_log_tail(task_id)
            await self._persist_task_run_snapshot(context)
            if completion_event is not None:
                completion_event.set()
            return

        context.status = TaskStatus.RUNNING
        context.started_at = self._now()
        context.updated_at = self._now()
        context.refresh_progress()
        if not self._is_queue_runner():
            await self._publish_event(
                "task_running",
                context,
                {
                    "task_id": context.task_id,
                    "status": context.status.value,
                    "started_at": context.started_at.isoformat(),
                },
            )

        plan = ExecutionPlan(
            total_nodes=context.execution_plan.total_nodes,
            execution_order=context.execution_plan.execution_order,
            parallel_groups=context.execution_plan.parallel_groups,
            estimated_duration_seconds=context.execution_plan.estimated_duration_seconds,
        )

        try:
            if self._is_queue_runner():
                if self._runner is None:
                    raise RuntimeError("Queue task runner is not configured")
                await self._runner.run(plan, context)
                return
            if self._dag_scheduler is not None and self._engine_client is not None:
                await self._execute_dag(context)
            elif self._runner is not None:
                if isinstance(self._runner, SerialTaskRunner):
                    raise RuntimeError(
                        "DAG scheduler is unavailable, so serial execution cannot start. "
                        "Check that init_dag_components succeeded at startup (see logs for errors)."
                    )
                await self._runner.run(plan, context)
            else:
                raise RuntimeError("No task runner available — DAG scheduler not wired")

            if self._is_cancel_requested(context):
                context.status = TaskStatus.CANCELLED
            else:
                context.status = self._calculate_final_status(context)

        except Exception as exc:  # noqa: BLE001
            context.status = TaskStatus.FAILED
            context.error = str(exc)

        context.completed_at = self._now()
        context.updated_at = self._now()
        context.duration_ms = self._duration_ms(context)
        self._sync_primary_result(context)
        context.end_summary = self._build_end_summary(context)
        if context.status == TaskStatus.FAILED and not context.error:
            context.error = self._first_node_error(context) or "Task execution failed"
        context.refresh_progress()

        if context.status == TaskStatus.FAILED:
            await self._publish_event(
                "task_failed",
                context,
                {
                    "task_id": context.task_id,
                    "status": context.status.value,
                    "error": context.error or "Task execution failed",
                    "failed_at": context.completed_at.isoformat(),
                },
            )

        await self._publish_event(
            "task_completed",
            context,
            {
                "task_id": context.task_id,
                "status": context.status.value,
                "started_at": context.started_at.isoformat() if context.started_at else None,
                "completed_at": context.completed_at.isoformat(),
                "duration_seconds": self._duration_seconds(context),
                "summary": self._build_task_summary(context),
            },
        )
        await self._await_event_log_tail(task_id)
        await self._persist_task_run_snapshot(context)
        if completion_event is not None:
            completion_event.set()

    async def _execute_dag(self, context: TaskContext) -> None:
        if (
            self._dag_scheduler is None
            or self._engine_client is None
            or self._auth_resolver is None
            or self._provider_store is None
            or context.workspace_id is None
        ):
            raise RuntimeError("DAG components are not initialised")

        result = await DurableWorkflowExecutionService(
            dag_scheduler=self._dag_scheduler,
            engine_client=self._engine_client,
            auth_resolver=self._auth_resolver,
            provider_store=self._provider_store,
        ).execute(
            context.workflow,
            task_id=context.task_id,
            input_bindings=context.input_files,
            workspace_id=context.workspace_id,
            cancel_check=lambda: self._is_cancel_requested(context),
        )

        for node_id, output in result.completed.items():
            node_state = context.node_states.get(node_id)
            if node_state is not None:
                node_state.status = NodeStatus.COMPLETED
                node_state.output = output.model_dump()
                node_state.completed_at = self._now()

                result_id = context.output_result_ids.get(node_id)
                if result_id is not None:
                    content = output.text or ""
                    source_fn = context.source_filename or "output"
                    metadata = OutputMetadata(
                        processing_time_ms=int(output.metadata.get("processing_time_ms", 0)),
                        page_count=int(output.metadata.get("page_count", 1)),
                        char_count=len(content),
                        word_count=len(content.split()) if content else 0,
                        source_filename=source_fn,
                    )
                    node_state.output = TaskResult(
                        result_id=result_id,
                        format="markdown",
                        filename=f"{source_fn}.md",
                        content_type="text/markdown",
                        storage_path="",
                        download_url=f"/api/tasks/{context.task_id}/results/{result_id}/download",
                        content=content,
                        metadata=metadata,
                    )

        for node_id, error_msg in result.failed.items():
            node_state = context.node_states.get(node_id)
            if node_state is not None:
                node_state.status = NodeStatus.FAILED
                node_state.error = error_msg
                node_state.completed_at = self._now()

        for node_id in result.skipped:
            node_state = context.node_states.get(node_id)
            if node_state is not None:
                node_state.status = NodeStatus.SKIPPED
                node_state.completed_at = self._now()

    async def _publish_event(
        self,
        event_type: str,
        context: TaskContext,
        data: dict[str, object],
    ) -> None:
        queue = self._event_queues.get(context.task_id)
        if queue is not None:
            event_payload: dict[str, object] = {"event": event_type, "data": data}
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event_payload)
                except asyncio.QueueFull:
                    pass
        self._append_event_log_fire_and_forget(
            task_id=context.task_id,
            event_type=event_type,
            data=data,
        )

    def _append_event_log_fire_and_forget(
        self,
        *,
        task_id: str,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        previous = self._event_log_append_tails.get(task_id)

        async def _run_append() -> None:
            # Keep append order stable per task while avoiding blocking the live event path.
            if previous is not None:
                try:
                    await previous
                except Exception:  # noqa: BLE001
                    pass

            await self._append_event_log(
                task_id=task_id,
                event_type=event_type,
                data=data,
            )

        append_task = asyncio.create_task(_run_append())
        self._event_log_append_tails[task_id] = append_task
        self._background_tasks.add(append_task)
        append_task.add_done_callback(self._background_tasks.discard)

        def _cleanup_tail(done_task: asyncio.Task[None]) -> None:
            if self._event_log_append_tails.get(task_id) is done_task:
                self._event_log_append_tails.pop(task_id, None)

        append_task.add_done_callback(_cleanup_tail)

    async def _await_event_log_tail(self, task_id: str) -> None:
        tail = self._event_log_append_tails.get(task_id)
        if tail is None:
            return
        try:
            await tail
        except Exception:  # noqa: BLE001
            pass

    async def _append_event_log(
        self,
        *,
        task_id: str,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        try:
            await self._event_log_repository.append(
                task_run_id=task_id,
                event_type=event_type,
                payload=data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EventLog dual-write failed: trace_id=%s task_id=%s "
                "table=task_event_logs op=INSERT event_type=%s error_type=%s",
                task_id,
                task_id,
                event_type,
                type(exc).__name__,
            )

    async def _persist_task_run_snapshot(
        self,
        context: TaskContext,
        *,
        workspace_id: str | None = None,
    ) -> None:
        try:
            results = self._build_result_snapshot_entries(context)
            await self._task_run_repository.upsert_snapshot(
                task_id=context.task_id,
                status=context.status.value,
                workflow_id=context.workflow_id,
                workflow_name=context.workflow_name,
                run_name=context.run_name,
                source=context.source,
                workspace_id=context.workspace_id or workspace_id,
                evaluation_run_id=context.evaluation_run_id,
                created_at=context.created_at,
                completed_at=context.completed_at,
                duration_ms=context.duration_ms,
                node_summary={
                    "total": context.progress.total_nodes,
                    "completed": context.progress.completed_nodes,
                    "failed": context.progress.failed_nodes,
                },
                result_preview=self._resolve_result_preview(context, results),
                results=results,
                error=context.error,
                input_files=[
                    {"node_id": node_id, **binding.model_dump(mode="json")}
                    for node_id, binding in context.input_files.items()
                ],
                workflow=context.workflow.model_dump(mode="json"),
                updated_at=context.updated_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "TaskRun snapshot persistence failed: task_id=%s error_type=%s",
                context.task_id,
                type(exc).__name__,
            )

    def _build_result_snapshot_entries(self, context: TaskContext) -> list[dict[str, object]]:
        outputs_by_node = {
            node_id: state.output
            for node_id, state in context.node_states.items()
            if state.output is not None
        }
        return build_final_output_snapshot_entries(
            context.workflow,
            outputs_by_node,
            task_id=context.task_id,
            task_duration_ms=context.duration_ms,
            result_ids_by_node=context.output_result_ids,
            source_filename=context.source_filename,
        )

    def _resolve_result_preview(
        self,
        context: TaskContext,
        results: list[dict[str, object]],
    ) -> str | None:
        if results:
            preview = results[0].get("result_preview")
            if isinstance(preview, str):
                return preview[:RESULT_PREVIEW_MAX_CHARS]

        if isinstance(context.result, TaskResult):
            return str(context.result.content)[:RESULT_PREVIEW_MAX_CHARS]

        return None

    def _build_task_summary(self, context: TaskContext) -> dict[str, object]:
        # Collect states for nodes connected to end node
        end_node = next((n for n in context.workflow.nodes if n.type == "end/final"), None)
        upstream_ids: set[str] = set()
        if end_node is not None:
            upstream_ids = {
                c.source for c in context.workflow.connections if c.target == end_node.id
            }
        output_states = [
            node for node in context.node_states.values() if node.node_id in upstream_ids
        ]
        summary: dict[str, object] = {
            "total_nodes": context.progress.total_nodes,
            "completed": context.progress.completed_nodes,
            "failed": context.progress.failed_nodes,
            "skipped": context.progress.skipped_nodes,
            "output_totals": {
                "total": len(output_states),
                "completed": sum(
                    1 for node in output_states if node.status == NodeStatus.COMPLETED
                ),
                "failed_or_skipped": sum(
                    1
                    for node in output_states
                    if node.status in {NodeStatus.FAILED, NodeStatus.SKIPPED}
                ),
            },
        }
        if context.end_summary is not None:
            summary["end_node"] = context.end_summary
        return summary

    def _infer_engine_type_for_node(self, context: TaskContext, node_id: str) -> str | None:
        """Extract engine type from a node's type string (e.g. engine/ocr -> ocr)."""
        node = next((n for n in context.workflow.nodes if n.id == node_id), None)
        if node is not None and node.type.startswith("engine/"):
            return node.type.split("/", 1)[1]
        return None

    def _sync_primary_result(self, context: TaskContext) -> None:
        # Collect states for nodes connected to end node
        end_node = next((n for n in context.workflow.nodes if n.type == "end/final"), None)
        upstream_ids: set[str] = set()
        if end_node is not None:
            upstream_ids = {
                c.source for c in context.workflow.connections if c.target == end_node.id
            }
        output_nodes = [
            node for node in context.node_states.values() if node.node_id in upstream_ids
        ]

        results: list[TaskResult] = []
        for node in output_nodes:
            if isinstance(node.output, TaskResult):
                results.append(node.output)

        if results:
            context.result = results[0]

    def _calculate_final_status(self, context: TaskContext) -> TaskStatus:
        # Check status of nodes connected to end node
        end_node = next((n for n in context.workflow.nodes if n.type == "end/final"), None)
        upstream_ids: set[str] = set()
        if end_node is not None:
            upstream_ids = {
                c.source for c in context.workflow.connections if c.target == end_node.id
            }
        output_node_states = [
            context.node_states[node_id]
            for node_id in upstream_ids
            if node_id in context.node_states
        ]

        if not output_node_states:
            return TaskStatus.COMPLETED if context.progress.failed_nodes == 0 else TaskStatus.FAILED

        completed = sum(1 for node in output_node_states if node.status.value == "completed")
        failed = sum(1 for node in output_node_states if node.status.value in {"failed", "skipped"})

        if completed == len(output_node_states):
            return TaskStatus.COMPLETED
        if completed > 0 and failed > 0:
            return TaskStatus.PARTIAL_COMPLETED
        if completed > 0:
            return TaskStatus.PARTIAL_COMPLETED
        return TaskStatus.FAILED

    def _build_end_summary(self, context: TaskContext) -> dict[str, object] | None:
        end_nodes = [node for node in context.workflow.nodes if node.type == "end/final"]
        if not end_nodes:
            return None

        # Collect upstream nodes connected to end
        end_node = end_nodes[0]
        upstream_ids = {c.source for c in context.workflow.connections if c.target == end_node.id}
        upstream_nodes = [n for n in context.workflow.nodes if n.id in upstream_ids]

        available_result_ids: list[str] = []
        failed_outputs: list[dict[str, object]] = []
        output_total = 0
        for node in upstream_nodes:
            output_total += 1
            state = context.node_states.get(node.id)
            if state is None:
                continue
            if state.status == NodeStatus.COMPLETED:
                result_id = context.output_result_ids.get(node.id)
                if result_id is not None:
                    available_result_ids.append(result_id)
            elif state.status in {NodeStatus.FAILED, NodeStatus.SKIPPED}:
                default_error_code = (
                    "NODE_DEPENDENCY_FAILED"
                    if state.status == NodeStatus.SKIPPED
                    else "NODE_EXECUTION_FAILED"
                )
                default_message = (
                    f"前置節點失敗或跳過，節點 {node.id} 已跳過"
                    if state.status == NodeStatus.SKIPPED
                    else f"節點 {node.id} 執行失敗"
                )
                failure_reason = node_failure_summary(
                    state.error,
                    default_error_code=default_error_code,
                    default_message=default_message,
                )
                failed_outputs.append(
                    {
                        "node_id": node.id,
                        "status": state.status.value,
                        "error_code": failure_reason["error_code"],
                        "message": failure_reason["message"],
                    }
                )

        return {
            "node_id": end_node.id,
            "status": context.status.value,
            "available_result_ids": available_result_ids,
            "failed_outputs": failed_outputs,
            "totals": {
                "outputs": output_total,
                "available": len(available_result_ids),
                "failed_or_skipped": len(failed_outputs),
            },
        }

    def _first_node_error(self, context: TaskContext) -> str | None:
        for node in context.node_states.values():
            message = node_failure_message(node.error)
            if message:
                return message
        return None

    def _is_cancel_requested(self, context: TaskContext) -> bool:
        # Cancellation can be toggled by concurrent API calls while the workflow is running.
        return bool(context.cancel_requested)

    def _resolve_input_bindings(
        self,
        workflow: WorkflowDefinition,
        file_ids: list[str],
        *,
        workspace_id: str | None = None,
        requested_by_user_id: str | None = None,
    ) -> dict[str, TaskInputFile]:
        input_nodes = [node for node in workflow.nodes if node.type.startswith("input/")]

        if not input_nodes:
            return {}

        placeholder_indexes: dict[str, int] = {}
        required_files = len(input_nodes)
        for node in input_nodes:
            placeholder_index = self._extract_file_placeholder_index(node.config.get("file"))
            if placeholder_index is None:
                continue
            placeholder_indexes[node.id] = placeholder_index
            required_files = max(required_files, placeholder_index + 1)

        if len(file_ids) < required_files:
            input_node_ids = ", ".join(node.id for node in input_nodes)
            raise ValueError(
                "file_ids 數量不足："
                f"Workflow 有 {len(input_nodes)} 個 input 節點（{input_node_ids}），"
                f"需要至少 {required_files} 個 file_ids，實際 {len(file_ids)} 個"
            )

        bindings: dict[str, TaskInputFile] = {}
        for index, node in enumerate(input_nodes):
            file_index = placeholder_indexes.get(node.id, index)
            file_id = file_ids[file_index]
            if workspace_id is not None:
                if requested_by_user_id is None:
                    raise ValueError(
                        "requested_by_user_id is required for workspace-scoped file access"
                    )
                record = self._file_store.get_owned(
                    file_id,
                    workspace_id,
                    requested_by_user_id,
                )
            else:
                record = self._file_store.get(file_id)
            if record is None:
                raise ValueError(f"找不到檔案：{file_id}")

            storage = getattr(self, "_storage", None)
            storage_root = getattr(storage, "storage_root", None)
            file_path = (
                str(resolve_storage_path(record.storage_path, storage_root))
                if storage_root is not None
                else record.storage_path
            )
            bindings[node.id] = TaskInputFile(
                file_id=record.file_id,
                file_path=file_path,
                filename=record.filename,
                mime_type=record.mime_type,
                size_bytes=record.size_bytes,
                workspace_id=record.workspace_id,
                uploaded_by_user_id=record.uploaded_by_user_id,
            )

        return bindings

    @staticmethod
    def _extract_file_placeholder_index(value: object) -> int | None:
        from app.services.workflow_utils import extract_file_placeholder_index

        return extract_file_placeholder_index(value)

    def _build_default_workflow(
        self,
        *,
        mime_type: str,
        engine: str,
        output_format: str,
    ) -> WorkflowDefinition:
        input_node_type = self._infer_input_node_type(mime_type)

        return WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type=input_node_type, config={"file": "$file_0"}),
                WorkflowNode(id="engine_1", type=f"engine/{engine}", config={}),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target="engine_1"),
                WorkflowConnection(source="engine_1", target="end_1"),
            ],
        )

    def _infer_input_node_type(self, mime_type: str) -> str:
        from app.services.workflow_utils import infer_input_node_type

        return infer_input_node_type(mime_type)

    def _infer_output_format(self, workflow: WorkflowDefinition) -> str:
        # Derive format from engine node types connected to end node
        end_node = next((n for n in workflow.nodes if n.type == "end/final"), None)
        if end_node is not None:
            for conn in workflow.connections:
                if conn.target == end_node.id:
                    upstream = next((n for n in workflow.nodes if n.id == conn.source), None)
                    if upstream is not None and upstream.type.startswith("engine/"):
                        return upstream.type.split("/", 1)[1]
        return "markdown"

    def _infer_engine(self, workflow: WorkflowDefinition) -> str:
        for node in workflow.nodes:
            node_type = str(node.type)
            if node_type.startswith("engine/"):
                return node_type.split("/", 1)[1]
        return "ocr"

    def _duration_seconds(self, context: TaskContext) -> int:
        if not context.started_at or not context.completed_at:
            return 0
        return max(int((context.completed_at - context.started_at).total_seconds()), 0)

    def _duration_ms(self, context: TaskContext) -> int | None:
        if not context.started_at or not context.completed_at:
            return None
        return max(int((context.completed_at - context.started_at).total_seconds() * 1000), 0)

    def _is_queue_runner(self) -> bool:
        return self._runner is not None and isinstance(self._runner, QueueTaskRunner)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
