from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Protocol, cast, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    from app.models.task import NodeState

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import State

from app.api.auth import require_workspace_capability
from app.api.error_response import error_response
from app.api.files import get_file_store
from app.api.task_helpers import (
    UploadRecord,
    build_result_entries_from_context,
    build_results_response,
    build_workflow_input_bindings,
    call_repository_method,
    cleanup_uploaded_files,
    collect_results_from_context,
    collect_results_from_snapshot,
    ensure_result_fields,
    extract_context_status,
    find_upstream_input_node,
    history_entry_from_snapshot,
    history_sort_key,
    is_results_ready_status,
    load_persisted_results_payload,
    parse_datetime_value,
    resolve_node_run_file_index,
    resolve_node_run_input_type,
    resolve_preview_from_context,
    resolve_status_from_snapshot_if_terminal,
    restore_task_result_from_snapshot_item,
    task_completed_event_payload,
    task_failed_event_payload,
    task_state_unavailable_response,
    truncate_result_preview,
    validate_and_store_upload,
    validate_upload,
)
from app.config import get_settings
from app.core.feature_flags import FeatureFlags
from app.db.session import SessionLocal
from app.models.execution import ExecutionEvent, NodeOutput
from app.models.task import TaskInputFile, TaskResult
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.providers.store import ProviderStore
from app.repositories.task_run_repository import TaskRunRepository, TaskRunSnapshot
from app.services.dag_scheduler import DAGScheduler
from app.services.durable_workflow_execution import build_composite_executor_runtime
from app.services.engine_client import EngineClient, make_node_executor
from app.services.event_store import EventStore
from app.services.node_registry import NodeRegistryService
from app.services.task_history import TaskHistoryService
from app.services.task_orchestrator import TaskOrchestrator
from app.services.workflow_utils import (
    extract_file_placeholder_index,
    infer_input_node_type,
)
from app.services.workflow_validator import WorkflowValidator
from app.services.workspace_access import ResolvedContext
from app.services.ws_manager import WSManager
from app.storage.local import get_storage
from app.storage.utils import ensure_path_within_root, ensure_path_within_roots
from app.utils.workflow_hash import compute_dag_hash

router = APIRouter()

SUPPORTED_ENGINES = {"ocr", "vlm", "text", "markitdown"}
SUPPORTED_OUTPUT_FORMATS = {"markdown", "plaintext", "yaml", "text"}
logger = logging.getLogger(__name__)


@runtime_checkable
class ModelDumpable(Protocol):
    def model_dump(self, *args: object, **kwargs: object) -> Any: ...


# ---------------------------------------------------------------------------
# Backward-compatible private aliases (used by existing callers / tests)
# ---------------------------------------------------------------------------
_truncate_result_preview = truncate_result_preview
_parse_datetime_value = parse_datetime_value
_history_sort_key = history_sort_key
_validate_and_store_upload = validate_and_store_upload
_cleanup_uploaded_files = cleanup_uploaded_files
_build_workflow_input_bindings = build_workflow_input_bindings
_extract_file_placeholder_index = extract_file_placeholder_index
_resolve_node_run_file_index = resolve_node_run_file_index
_find_upstream_input_node = find_upstream_input_node
_resolve_node_run_input_type = resolve_node_run_input_type
_infer_input_node_type = infer_input_node_type
_build_result_entries_from_context = build_result_entries_from_context
_ensure_result_fields = ensure_result_fields
_build_results_response = build_results_response
_extract_context_status = extract_context_status
_resolve_status_from_snapshot_if_terminal = resolve_status_from_snapshot_if_terminal
_is_results_ready_status = is_results_ready_status
_task_state_unavailable_response = task_state_unavailable_response
_collect_results_from_context = collect_results_from_context
_collect_results_from_snapshot = collect_results_from_snapshot
_restore_task_result_from_snapshot_item = restore_task_result_from_snapshot_item
_task_completed_event_payload = task_completed_event_payload
_task_failed_event_payload = task_failed_event_payload
_history_entry_from_snapshot = history_entry_from_snapshot
_call_repository_method = call_repository_method
_load_persisted_results_payload = load_persisted_results_payload
_resolve_preview_from_context = resolve_preview_from_context


def _validation_issue_payload(error: object) -> dict[str, object]:
    return {
        "code": getattr(error, "code", "UNKNOWN"),
        "message": getattr(error, "message", "Validation failed"),
        "details": getattr(error, "details", {}),
        "severity": getattr(error, "severity", "blocking"),
        "node_id": getattr(error, "node_id", None),
        "field": getattr(error, "field", None),
    }


# ---------------------------------------------------------------------------
# DAG component assembly & in-memory running tasks
# ---------------------------------------------------------------------------


@dataclass
class RunningTaskContext:
    """Lightweight holder for an actively executing workflow run."""

    task_id: str
    run_id: str
    workflow: WorkflowDefinition
    asyncio_task: asyncio.Task
    workspace_id: str | None = None
    cancel_requested: bool = False
    input_files: list[dict] | None = None  # [{"name": ..., "size": ...}] for hash computation


def init_dag_components(app_state: State) -> None:
    """Create DAGScheduler, EngineClient, EventStore and attach to *app_state*.

    Called once from ``lifespan()`` in ``app/main.py``.
    """
    from app.services.ws_manager import ws_manager

    node_registry = NodeRegistryService()
    event_store = EventStore(session_factory=SessionLocal)
    settings = get_settings()
    engine_client = EngineClient(settings=settings)
    storage = get_storage()
    dag_scheduler = DAGScheduler(
        event_store=event_store, node_registry=node_registry, storage=storage
    )

    # Wire event publishing to WebSocket fan-out
    def _publish_to_ws(event: ExecutionEvent) -> None:
        """Bridge sync event_store.append → async ws_manager.publish."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(ws_manager.publish(event.workflow_run_id, event))
        except RuntimeError:
            pass  # No running loop — skip WS publish

    event_store.set_publish_callback(_publish_to_ws)

    app_state.dag_scheduler = dag_scheduler
    app_state.engine_client = engine_client
    app_state.event_store = event_store
    app_state.node_registry = node_registry
    app_state.running_tasks = {}

    logger.info("DAG components initialised (DAGScheduler + EngineClient + EventStore)")


@lru_cache(maxsize=1)
def get_task_run_repository() -> TaskRunRepository:
    return TaskRunRepository()


@lru_cache(maxsize=1)
def get_task_orchestrator() -> TaskOrchestrator:
    from app.main import app

    return cast(TaskOrchestrator, app.state.task_orchestrator)


def reset_task_orchestrator() -> None:
    get_task_orchestrator.cache_clear()


@lru_cache(maxsize=1)
def get_sse_manager() -> WSManager:
    from app.services.ws_manager import ws_manager

    return ws_manager


def _matches_workspace(task_workspace_id: str | None, workspace_id: str | None) -> bool:
    return workspace_id is None or task_workspace_id == workspace_id


async def _get_workspace_snapshot(
    repository: TaskRunRepository,
    task_id: str,
    workspace_id: str | None,
) -> TaskRunSnapshot | None:
    return await repository.get_snapshot(task_id, workspace_id=workspace_id)


async def _task_visible_in_workspace(
    *,
    task_id: str,
    running_tasks: dict[str, RunningTaskContext],
    repository: TaskRunRepository,
    workspace_id: str | None,
) -> bool:
    ctx = running_tasks.get(task_id)
    if ctx is not None:
        return _matches_workspace(ctx.workspace_id, workspace_id)
    return await _get_workspace_snapshot(repository, task_id, workspace_id) is not None


WorkflowRunContext = Annotated[
    ResolvedContext, Depends(require_workspace_capability("workflow.run"))
]
RunViewContext = Annotated[ResolvedContext, Depends(require_workspace_capability("run.view"))]
RunCancelContext = Annotated[ResolvedContext, Depends(require_workspace_capability("run.cancel"))]
WorkflowEditDraftContext = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("workflow.edit_draft")),
]
WorkflowRunRequired = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("workflow.run")),
]


# ---------------------------------------------------------------------------
# DAG execution helpers
# ---------------------------------------------------------------------------


def _start_dag_run(
    *,
    task_id: str,
    run_id: str,
    workflow: WorkflowDefinition,
    dag_scheduler: DAGScheduler,
    engine_client: EngineClient,
    event_store: EventStore,
    running_tasks: dict[str, RunningTaskContext],
    created_at: datetime,
    input_bindings: dict[str, "TaskInputFile"] | None = None,
    auth_resolver: object | None = None,
    provider_store: ProviderStore | None = None,
    start_nodes: set[str] | None = None,
    input_files: list[dict] | None = None,
    dag_hash: str | None = None,
    input_files_meta: list[dict] | None = None,
    workspace_id: str | None = None,
) -> None:
    """Kick off DAGScheduler.run() as a background asyncio.Task."""

    async def _execute() -> None:
        # Resolve $file_N placeholders in input node configs
        if input_bindings:
            for n in workflow.nodes:
                if n.type.startswith("input/") and "file" in n.config:
                    binding = input_bindings.get(n.id)
                    if binding:
                        n.config["file"] = binding.file_path

        base_executor = make_node_executor(
            engine_client,
            auth_resolver=auth_resolver,
            provider_resolver=(
                lambda provider_id: (
                    provider_store.get_for_runtime(provider_id, workspace_id)
                    if provider_store is not None and workspace_id is not None
                    else None
                )
            ),
        )
        composite = build_composite_executor_runtime(
            base_executor=base_executor,
            workflow=workflow,
        )
        executor = composite.executor
        started_at = time.monotonic()
        final_status = "completed"
        error_msg: str | None = None
        result_preview: str | None = None
        results_list: list[dict] | None = None
        try:
            dag_result = await dag_scheduler.run(
                workflow,
                node_executor=executor,
                run_id=run_id,
                start_nodes=start_nodes,
            )
            state = dag_result.completed
            # Derive results from nodes connected to end node
            end_node = next((n for n in workflow.nodes if n.type == "end/final"), None)
            upstream_of_end: set[str] = set()
            if end_node is not None:
                upstream_of_end = {
                    c.source for c in workflow.connections if c.target == end_node.id
                }
            results_list = []
            for node_id in upstream_of_end:
                output = state.get(node_id)
                if output is not None:
                    results_list.append(_build_result_from_node_output(output, node_id, task_id))
                    if result_preview is None and output.text:
                        result_preview = output.text[:500]

            # If any upstream engine node is missing from state, it failed → workflow failed
            all_node_ids = {n.id for n in workflow.nodes}
            completed_ids = set(state.keys())
            if completed_ids < all_node_ids:
                final_status = "failed"
                error_msg = f"部分節點未完成：{all_node_ids - completed_ids}"
        except Exception as exc:
            final_status = "failed"
            error_msg = str(exc)[:500]
            logger.error(
                "DAG run %s failed error_type=%s",
                run_id,
                type(exc).__name__,
            )

        duration_ms = int((time.monotonic() - started_at) * 1000)
        completed_at = datetime.now(timezone.utc)

        # Compute node summary from events
        node_summary: dict[str, int] = {}
        try:
            events = event_store.get_events(run_id)
            for e in events:
                if e.event_type in ("completed", "failed", "skipped"):
                    node_summary[e.event_type] = node_summary.get(e.event_type, 0) + 1
        except Exception:
            pass

        # Persist final snapshot
        task_repo = get_task_run_repository()
        try:
            await task_repo.upsert_snapshot(
                task_id=task_id,
                status=final_status,
                workflow_id=None,
                workflow_name=None,
                run_name=None,
                workspace_id=workspace_id,
                created_at=created_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                node_summary=node_summary or None,
                result_preview=result_preview,
                results=results_list,
                error=error_msg,
                dag_hash=dag_hash,
                input_files=input_files_meta,
                updated_at=completed_at,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist final snapshot for %s error_type=%s",
                task_id,
                type(exc).__name__,
            )

        # Remove from running_tasks so history endpoint shows final status from DB
        running_tasks.pop(task_id, None)

        # Broadcast workflow_state to WebSocket subscribers
        try:
            from app.services.ws_manager import ws_manager as _ws

            logger.info("Broadcasting workflow_state: run_id=%s status=%s", run_id, final_status)
            await _ws.send_workflow_state(run_id, final_status)
        except Exception as exc:
            logger.warning(
                "Failed to broadcast workflow_state run_id=%s error_type=%s",
                run_id,
                type(exc).__name__,
            )

        await composite.aclose()

    bg_task = asyncio.create_task(_execute())
    running_tasks[task_id] = RunningTaskContext(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow,
        asyncio_task=bg_task,
        workspace_id=workspace_id,
        input_files=input_files,
    )


def _node_output_to_result(output: NodeOutput, node_id: str, task_id: str) -> dict:
    """Convert a NodeOutput to a result dict for API response / snapshot."""
    return {
        "result_id": f"{task_id}_{node_id}",
        "node_id": node_id,
        "format": "markdown",
        "content_type": "text/markdown",
        "content": output.text or "",
        "metadata": output.metadata or {},
        "binary_count": len(output.binary) if output.binary else 0,
    }


def _build_result_from_node_output(
    output: NodeOutput,
    node_id: str,
    task_id: str,
    storage_path: str = "",
) -> dict:
    """Convert NodeOutput to a TaskResult-compatible dict."""
    import json as _json

    content = _json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2)

    return {
        "result_id": f"r_{task_id}_{node_id}",
        "format": "json",
        "file": {
            "filename": f"{node_id}_output.json",
            "size_bytes": len(content.encode("utf-8")),
            "content_type": "application/json",
            "download_url": f"/api/tasks/{task_id}/results/r_{task_id}_{node_id}/download",
        },
        "content": content,
        "metadata": output.metadata or {},
    }


# ---------------------------------------------------------------------------
# Node state reconstruction from EventStore
# ---------------------------------------------------------------------------


def _reconstruct_node_states(
    run_id: str,
    workflow: WorkflowDefinition,
    event_store: EventStore,
) -> dict[str, NodeState]:
    """Iterate EventStore events for *run_id* and build per-node state."""
    from app.models.task import NodeState, NodeStatus

    events = event_store.get_events(run_id)
    node_states: dict[str, NodeState] = {}
    for node in workflow.nodes:
        state = NodeState(node_id=node.id, node_type=node.type, status=NodeStatus.PENDING)
        for e in events:
            if e.node_id != node.id:
                continue
            if e.event_type == "started":
                state.status = NodeStatus.RUNNING
                state.started_at = datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
            elif e.event_type == "completed":
                state.status = NodeStatus.COMPLETED
                state.completed_at = datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
                state.output = e.output
            elif e.event_type == "failed":
                state.status = NodeStatus.FAILED
                state.completed_at = datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
                state.error = e.error.message if e.error else "Unknown error"
            elif e.event_type == "skipped":
                state.status = NodeStatus.SKIPPED
                state.completed_at = datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
        node_states[node.id] = state
    return node_states


def _find_downstream_nodes(workflow: WorkflowDefinition, node_id: str) -> set[str]:
    """Find all nodes downstream of *node_id* via BFS on connections."""
    adjacency: dict[str, list[str]] = {}
    for conn in workflow.connections:
        adjacency.setdefault(conn.source, []).append(conn.target)
    visited: set[str] = set()
    queue = list(adjacency.get(node_id, []))
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency.get(current, []))
    return visited


def _node_output_from_events(
    run_id: str, node_id: str, event_store: EventStore
) -> tuple[object | None, str, str, str]:
    """Find last completed/failed event for node_id, return (output, status, error, node_type)."""
    from app.models.task import NodeStatus

    events = event_store.get_events(run_id)
    node_type = ""
    output: object | None = None
    error: str | None = None
    status = NodeStatus.PENDING.value

    for e in events:
        if e.node_id != node_id:
            continue
        node_type = e.node_type
        if e.event_type == "started":
            status = NodeStatus.RUNNING.value
            datetime.fromtimestamp(e.timestamp, tz=timezone.utc)
        elif e.event_type == "completed":
            status = NodeStatus.COMPLETED.value
            output = e.output
        elif e.event_type == "failed":
            status = NodeStatus.FAILED.value
            error = e.error.message if e.error else "Unknown error"
        elif e.event_type == "skipped":
            status = NodeStatus.SKIPPED.value

    return output, status, error or "", node_type


def _upstream_output_from_events(
    run_id: str,
    node_id: str,
    event_store: EventStore,
) -> object | None:
    """Return the completed output feeding a node's latest execution."""
    events = event_store.get_events(run_id)
    source_node_ids: list[str] = []

    for event in reversed(events):
        if event.node_id == node_id and event.event_type == "started" and event.resolved_inputs:
            source_node_ids = [
                resolved.source_node_id for resolved in event.resolved_inputs.values()
            ]
            break

    for source_node_id in source_node_ids:
        for event in reversed(events):
            if (
                event.node_id == source_node_id
                and event.event_type == "completed"
                and event.output is not None
            ):
                return event.output

    return None


@router.post("/tasks", response_model=None)
async def create_task(
    request: Request,
    ctx: WorkflowEditDraftContext,
    _run_ctx: WorkflowRunRequired,
    file: Annotated[UploadFile | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    workflow: Annotated[str | None, Form()] = None,
    file_ids: Annotated[str | None, Form()] = None,
    engine: Annotated[str, Form()] = "ocr",
    output_format: Annotated[str, Form()] = "markdown",
    run_name: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    settings = get_settings()
    dag_scheduler: DAGScheduler = request.app.state.dag_scheduler
    engine_client: EngineClient = request.app.state.engine_client
    event_store: EventStore = request.app.state.event_store
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks

    # Sanitize run_name: strip whitespace, enforce max length, remove
    # leading formula characters (=, +, -, @) that could trigger injection
    # if the value is ever exported to CSV/Excel.
    if run_name is not None:
        run_name = run_name.strip()
        if len(run_name) > 200:
            run_name = run_name[:200]
        if not run_name:
            run_name = None
        elif run_name[0] in ("=", "+", "-", "@", "\t", "\r"):
            run_name = "'" + run_name

    if workflow is not None:
        try:
            workflow_payload = json.loads(workflow)
            definition = WorkflowDefinition.model_validate(workflow_payload)
        except (json.JSONDecodeError, ValueError) as exc:
            return error_response(400, "WORKFLOW_VALIDATION_ERROR", f"Workflow JSON 無效：{exc}")

        parsed_file_ids: list[str] = []
        if file_ids:
            try:
                parsed = json.loads(file_ids)
                if isinstance(parsed, list):
                    parsed_file_ids = [str(item) for item in parsed]
            except json.JSONDecodeError:
                return error_response(
                    400, "WORKFLOW_VALIDATION_ERROR", "file_ids 必須為 JSON array"
                )

        uploaded_files: list[UploadRecord] = []
        for upload in files or []:
            uploaded = await validate_and_store_upload(upload, settings)
            if isinstance(uploaded, JSONResponse):
                await cleanup_uploaded_files(uploaded_files, settings)
                return uploaded
            uploaded_files.append(uploaded)

        if file is not None:
            uploaded = await validate_and_store_upload(file, settings)
            if isinstance(uploaded, JSONResponse):
                await cleanup_uploaded_files(uploaded_files, settings)
                return uploaded
            uploaded_files.append(uploaded)

        input_bindings: dict[str, TaskInputFile] | None = None
        if uploaded_files:
            try:
                input_bindings = build_workflow_input_bindings(definition, uploaded_files)
            except ValueError as exc:
                await cleanup_uploaded_files(uploaded_files, settings)
                return error_response(400, "WORKFLOW_VALIDATION_ERROR", str(exc))
        elif parsed_file_ids:
            if ctx.workspace_id is None:
                return error_response(404, "FILE_NOT_FOUND", "找不到目前工作區使用者上傳的檔案")
            records = [
                get_file_store().get_owned(file_id, ctx.workspace_id, ctx.user.id)
                for file_id in parsed_file_ids
            ]
            if any(record is None for record in records):
                return error_response(404, "FILE_NOT_FOUND", "找不到目前工作區使用者上傳的檔案")
            input_bindings = build_workflow_input_bindings(
                definition,
                [
                    {
                        "storage_path": record.storage_path,
                        "filename": record.filename,
                        "mime_type": record.mime_type,
                        "size_bytes": record.size_bytes,
                    }
                    for record in records
                    if record is not None
                ],
            )

        validator = WorkflowValidator(
            node_registry=NodeRegistryService(),
            provider_store=request.app.state.provider_store,
        )
        validation_result = validator.validate(definition, workspace_id=ctx.workspace_id)
        if validation_result.errors:
            logger.error(
                "Workflow validation failed error_count=%d codes=%s node_ids=%s",
                len(validation_result.errors),
                [error.code for error in validation_result.errors],
                [error.node_id for error in validation_result.errors],
            )
            await cleanup_uploaded_files(uploaded_files, settings)
            return error_response(
                400,
                "WORKFLOW_VALIDATION_ERROR",
                "Workflow 定義驗證失敗",
                details={
                    "errors": [
                        _validation_issue_payload(error) for error in validation_result.errors
                    ],
                    "warnings": [
                        _validation_issue_payload(warning) for warning in validation_result.warnings
                    ],
                },
            )

        task_id = f"task_{uuid4().hex[:12]}"
        run_id = task_id  # Use task_id as run_id so WebSocket can subscribe by task_id
        created_at = datetime.now(timezone.utc)

        # Compute DAG hash for change detection
        dag_hash = compute_dag_hash(
            [{"id": n.id, "type": n.type} for n in definition.nodes],
            [
                {
                    "source": e.source,
                    "target": e.target,
                    "sourceHandle": e.source_port,
                    "targetHandle": e.target_port,
                }
                for e in definition.connections
            ],
            {n.id: n.config for n in definition.nodes},
        )
        input_files_meta = [
            {"name": f["filename"], "size": f["size_bytes"]} for f in uploaded_files
        ]

        # Clear any previous run context for this workflow (re-run support)
        # This handles the case where user clicks Run on an already-completed/failed workflow

        # Persist initial snapshot
        task_repo = get_task_run_repository()
        try:
            await task_repo.upsert_snapshot(
                task_id=task_id,
                status="pending",
                workflow_id=None,
                workflow_name=None,
                run_name=run_name,
                workspace_id=ctx.workspace_id,
                created_at=created_at,
                completed_at=None,
                duration_ms=None,
                node_summary=None,
                result_preview=None,
                results=None,
                error=None,
                dag_hash=dag_hash,
                input_files=input_files_meta,
                workflow=definition.model_dump(mode="json"),
                updated_at=created_at,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist initial snapshot for %s error_type=%s",
                task_id,
                type(exc).__name__,
            )

        # Build execution plan for response
        total_nodes = len(definition.nodes)
        execution_plan = {
            "total_nodes": total_nodes,
            "execution_order": [[n.id] for n in definition.nodes],
            "parallel_groups": total_nodes,
        }

        # Kick off DAG execution in background
        _start_dag_run(
            task_id=task_id,
            run_id=run_id,
            workflow=definition,
            dag_scheduler=dag_scheduler,
            engine_client=engine_client,
            event_store=event_store,
            running_tasks=running_tasks,
            created_at=created_at,
            input_bindings=input_bindings,
            auth_resolver=getattr(request.app.state, "auth_resolver", None),
            provider_store=getattr(request.app.state, "provider_store", None),
            dag_hash=dag_hash,
            input_files_meta=input_files_meta,
            workspace_id=ctx.workspace_id,
        )

        return JSONResponse(
            status_code=202,
            content={
                "task_id": task_id,
                "run_name": run_name,
                "status": "pending",
                "created_at": created_at.isoformat(),
                "dag_hash": dag_hash,
                "input_files": input_files_meta,
                "workflow": definition.model_dump(mode="json"),
                "execution_plan": execution_plan,
            },
        )

    if file is None:
        return error_response(400, "EMPTY_FILE", "檔案不可為空")

    if engine not in SUPPORTED_ENGINES:
        return error_response(400, "UNSUPPORTED_ENGINE", f"不支援的引擎：{engine}")

    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        return error_response(
            400, "UNSUPPORTED_OUTPUT_FORMAT", f"不支援的輸出格式：{output_format}"
        )

    content = await validate_upload(file, settings)
    if isinstance(content, JSONResponse):
        return content

    mime_type = (file.content_type or "").lower()

    # Build a default 3-node workflow for simple file upload
    input_type = "input/text" if mime_type.startswith("text/") else "input/image"
    engine_type = f"engine/{engine}"
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type=input_type, config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type=engine_type, config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )

    task_id = f"task_{uuid4().hex[:12]}"
    run_id = task_id  # Use task_id as run_id so WebSocket can subscribe by task_id
    created_at = datetime.now(timezone.utc)

    task_repo = get_task_run_repository()
    try:
        await task_repo.upsert_snapshot(
            task_id=task_id,
            status="pending",
            workflow_id=None,
            workflow_name=None,
            run_name=None,
            workspace_id=ctx.workspace_id,
            created_at=created_at,
            completed_at=None,
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            updated_at=created_at,
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist initial snapshot for %s error_type=%s",
            task_id,
            type(exc).__name__,
        )

    # --- Workflow Hash computation (simple upload path) ---
    node_dicts = [{"id": n.id, "type": n.type} for n in definition.nodes]
    edge_dicts = [
        {
            "source": c.source,
            "target": c.target,
            "sourceHandle": c.source_port,
            "targetHandle": c.target_port,
        }
        for c in definition.connections
    ]
    node_configs = {n.id: n.config for n in definition.nodes}
    dag_hash = compute_dag_hash(node_dicts, edge_dicts, node_configs)
    input_files_meta = [{"name": file.filename or "upload", "size": len(content)}]

    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=definition,
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        event_store=event_store,
        running_tasks=running_tasks,
        created_at=created_at,
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        dag_hash=dag_hash,
        input_files_meta=input_files_meta,
        workspace_id=ctx.workspace_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "status": "pending",
            "created_at": created_at.isoformat(),
            "dag_hash": dag_hash,
            "input_files": input_files_meta,
        },
    )


@router.post("/tasks/node-run", response_model=None)
async def create_node_run_task(
    request: Request,
    ctx: WorkflowEditDraftContext,
    _run_ctx: WorkflowRunRequired,
    workflow: Annotated[str | None, Form()] = None,
    node_id: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    file_ids: Annotated[str | None, Form()] = None,
    output_format: Annotated[str, Form()] = "markdown",
) -> JSONResponse:
    settings = get_settings()
    dag_scheduler: DAGScheduler = request.app.state.dag_scheduler
    engine_client: EngineClient = request.app.state.engine_client
    event_store: EventStore = request.app.state.event_store
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks

    if workflow is None:
        return error_response(400, "WORKFLOW_VALIDATION_ERROR", "node-run 需要 workflow 參數")
    if not node_id:
        return error_response(400, "WORKFLOW_VALIDATION_ERROR", "node-run 需要 node_id 參數")
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        return error_response(
            400, "UNSUPPORTED_OUTPUT_FORMAT", f"不支援的輸出格式：{output_format}"
        )

    try:
        workflow_payload = json.loads(workflow)
        definition = WorkflowDefinition.model_validate(workflow_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        return error_response(400, "WORKFLOW_VALIDATION_ERROR", f"Workflow JSON 無效：{exc}")

    ALLOWED_NODE_RUN_PREFIXES = ("input/", "processor/", "engine/")
    target_node = definition.get_node(node_id)
    if target_node is None:
        return error_response(400, "WORKFLOW_VALIDATION_ERROR", f"node-run 找不到節點：{node_id}")
    if not any(target_node.type.startswith(p) for p in ALLOWED_NODE_RUN_PREFIXES):
        return error_response(
            400,
            "WORKFLOW_VALIDATION_ERROR",
            f"node-run 不支援此節點類型：{target_node.type}",
        )

    uploaded_files: list[UploadRecord] = []

    async def _node_run_error(code: int, error_code: str, message: str) -> JSONResponse:
        await cleanup_uploaded_files(uploaded_files, settings)
        return error_response(code, error_code, message)

    for upload in files or []:
        uploaded = await validate_and_store_upload(upload, settings)
        if isinstance(uploaded, JSONResponse):
            await cleanup_uploaded_files(uploaded_files, settings)
            return uploaded
        uploaded_files.append(uploaded)

    if file is not None:
        uploaded = await validate_and_store_upload(file, settings)
        if isinstance(uploaded, JSONResponse):
            await cleanup_uploaded_files(uploaded_files, settings)
            return uploaded
        uploaded_files.append(uploaded)

    parsed_file_ids: list[str] = []
    if file_ids:
        try:
            parsed = json.loads(file_ids)
            if isinstance(parsed, list):
                parsed_file_ids = [str(item) for item in parsed]
        except json.JSONDecodeError:
            return await _node_run_error(
                400,
                "WORKFLOW_VALIDATION_ERROR",
                "file_ids 必須為 JSON array",
            )

    if not uploaded_files and not parsed_file_ids:
        return await _node_run_error(400, "EMPTY_FILE", "node-run 需要至少一個輸入檔案")

    input_node = find_upstream_input_node(definition, node_id)
    selected_upload: UploadRecord | None = None
    selected_file_id: str | None = None

    if uploaded_files:
        try:
            upload_index = resolve_node_run_file_index(input_node, len(uploaded_files))
        except ValueError as exc:
            return await _node_run_error(400, "WORKFLOW_VALIDATION_ERROR", str(exc))
        selected_upload = uploaded_files[upload_index]
    else:
        try:
            file_id_index = resolve_node_run_file_index(input_node, len(parsed_file_ids))
        except ValueError as exc:
            return await _node_run_error(400, "WORKFLOW_VALIDATION_ERROR", str(exc))
        selected_file_id = parsed_file_ids[file_id_index]

    try:
        input_node_type = resolve_node_run_input_type(
            input_node=input_node,
            upload_record=selected_upload,
            file_id=selected_file_id,
            file_store_getter=get_file_store,
        )
    except ValueError as exc:
        return await _node_run_error(400, "WORKFLOW_VALIDATION_ERROR", str(exc))

    # Build different synthetic workflows based on target node type
    if target_node.type.startswith("input/"):
        # Input node: single-node workflow, file binds directly to target
        node_run_workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id=node_id, type=target_node.type, config={"file": "$file_0"}),
            ],
            connections=[],
        )
    elif target_node.type.startswith("processor/"):
        # Processor node: 2-node chain (input → processor), no output node
        node_run_workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type=input_node_type, config={"file": "$file_0"}),
                WorkflowNode(id=node_id, type=target_node.type, config=target_node.config),
            ],
            connections=[
                WorkflowConnection(source="input_1", target=node_id),
            ],
        )
    else:
        # Engine node: 3-node chain (input → engine → end)
        node_run_workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_1", type=input_node_type, config={"file": "$file_0"}),
                WorkflowNode(id=node_id, type=target_node.type, config=target_node.config),
                WorkflowNode(id="end_1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="input_1", target=node_id),
                WorkflowConnection(source=node_id, target="end_1"),
            ],
        )

    # Resolve actual file path and inject into synthetic workflow
    resolved_file_path: str | None = None
    if selected_upload is not None:
        resolved_file_path = str(selected_upload["storage_path"])
    elif selected_file_id is not None:
        if ctx.workspace_id is None:
            return await _node_run_error(404, "FILE_NOT_FOUND", f"找不到檔案：{selected_file_id}")
        store = get_file_store()
        record = store.get_owned(selected_file_id, ctx.workspace_id, ctx.user.id)
        if record is None:
            return await _node_run_error(400, "FILE_NOT_FOUND", f"找不到檔案：{selected_file_id}")
        resolved_file_path = record.storage_path

    if resolved_file_path is not None:
        for n in node_run_workflow.nodes:
            file_val = n.config.get("file", "")
            if isinstance(file_val, str) and file_val.startswith("$file_"):
                n.config["file"] = resolved_file_path
                break

    task_id = f"task_{uuid4().hex[:12]}"
    run_id = task_id  # Use task_id as run_id so WebSocket can subscribe by task_id
    created_at = datetime.now(timezone.utc)

    task_repo = get_task_run_repository()
    try:
        await task_repo.upsert_snapshot(
            task_id=task_id,
            status="pending",
            workflow_id=None,
            workflow_name=None,
            run_name=None,
            workspace_id=ctx.workspace_id,
            created_at=created_at,
            completed_at=None,
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            updated_at=created_at,
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist initial snapshot for %s error_type=%s",
            task_id,
            type(exc).__name__,
        )

    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=node_run_workflow,
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        event_store=event_store,
        running_tasks=running_tasks,
        created_at=created_at,
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        workspace_id=ctx.workspace_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "status": "pending",
            "created_at": created_at.isoformat(),
            "node_id": node_id,
            "output_format": output_format,
        },
    )


@router.get("/tasks/history", response_model=None)
async def list_task_history(
    request: Request,
    auth_ctx: RunViewContext,
    page: int = 1,
    limit: int = 20,
    status: str = "all",
    workflow_id: str | None = None,
) -> JSONResponse:
    normalized_status = status.lower().strip()
    if normalized_status not in TaskHistoryService.VALID_STATUSES:
        return error_response(
            400,
            "INVALID_STATUS_FILTER",
            f"不支援的 status 篩選：{status}",
        )

    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    task_run_repository = get_task_run_repository()

    # Load persisted snapshots
    snapshot_items: list[dict[str, object]] = []
    try:
        snapshots = await task_run_repository.list_snapshots(
            status="all",
            workflow_id=workflow_id,
            workspace_id=auth_ctx.workspace_id,
        )
    except Exception:  # noqa: BLE001
        snapshots = []

    for snapshot in snapshots:
        item = history_entry_from_snapshot(snapshot)
        if item is not None:
            snapshot_items.append(item)

    # Build merged dict from snapshots
    merged: dict[str, dict[str, object]] = {}
    for item in snapshot_items:
        merged[str(item["task_id"])] = item

    # Merge in running tasks — they take precedence for status
    for tid, task_ctx in running_tasks.items():
        if not _matches_workspace(task_ctx.workspace_id, auth_ctx.workspace_id):
            continue
        existing = merged.get(tid, {})
        entry = dict(existing)
        entry["task_id"] = tid
        entry["status"] = "cancelled" if task_ctx.cancel_requested else "running"
        if "created_at" not in entry or entry["created_at"] is None:
            entry["created_at"] = datetime.now(timezone.utc).isoformat()
        merged[tid] = entry

    # Apply status filter after merge
    if normalized_status != "all":
        merged = {
            tid: entry
            for tid, entry in merged.items()
            if str(entry.get("status", "")).lower() == normalized_status
        }

    data = sorted(merged.values(), key=history_sort_key, reverse=True)

    safe_page = max(page, 1)
    safe_limit = max(limit, 1)
    total = len(data)
    start = (safe_page - 1) * safe_limit
    end = start + safe_limit
    paged = data[start:end]

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": paged,
            "meta": {
                "total": total,
                "page": safe_page,
                "limit": safe_limit,
            },
        },
    )


@router.get("/tasks/{task_id}", response_model=None)
async def get_task_status(
    request: Request,
    task_id: str,
    auth_ctx: RunViewContext,
) -> JSONResponse:
    from app.models.task import NodeStatus

    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    task_run_repository = get_task_run_repository()

    ctx = running_tasks.get(task_id)

    if ctx is not None:
        if not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        # Running task — reconstruct from EventStore events
        node_states = _reconstruct_node_states(ctx.run_id, ctx.workflow, event_store)

        if ctx.cancel_requested:
            overall_status = "cancelled"
        elif any(ns.status == NodeStatus.RUNNING for ns in node_states.values()):
            overall_status = "running"
        elif any(ns.status == NodeStatus.FAILED for ns in node_states.values()):
            overall_status = "failed"
        elif all(
            ns.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED) for ns in node_states.values()
        ):
            overall_status = "completed"
        else:
            overall_status = "running"

        node_status_list = [
            {
                "node_id": ns.node_id,
                "node_type": ns.node_type,
                "status": ns.status.value,
                "started_at": ns.started_at.isoformat() if ns.started_at else None,
                "completed_at": ns.completed_at.isoformat() if ns.completed_at else None,
                "error": _serialize_node_error(ns.error),
                "progress": ns.progress,
            }
            for ns in node_states.values()
        ]
        node_states_map = {item["node_id"]: item for item in node_status_list}

        total = len(ctx.workflow.nodes)
        completed = sum(1 for ns in node_states.values() if ns.status == NodeStatus.COMPLETED)
        failed = sum(1 for ns in node_states.values() if ns.status == NodeStatus.FAILED)
        pending = sum(1 for ns in node_states.values() if ns.status == NodeStatus.PENDING)

        # Augment with snapshot timestamps
        created_at = datetime.now(timezone.utc)
        completed_at: datetime | None = None
        snapshot: TaskRunSnapshot | None = None
        try:
            snapshot = await _get_workspace_snapshot(
                task_run_repository,
                task_id,
                auth_ctx.workspace_id,
            )
            if snapshot and snapshot.created_at:
                created_at = snapshot.created_at
            if snapshot and snapshot.completed_at:
                completed_at = snapshot.completed_at
        except Exception:
            pass

        payload: dict[str, object] = {
            "task_id": task_id,
            "run_name": None,
            "status": overall_status,
            "created_at": created_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": created_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "progress": {
                "total_nodes": total,
                "completed_nodes": completed,
                "failed_nodes": failed,
                "pending_nodes": pending,
                "skipped_nodes": sum(
                    1 for ns in node_states.values() if ns.status == NodeStatus.SKIPPED
                ),
                "current_node": None,
                "percentage": int(completed / total * 100) if total else 0,
            },
            "node_status": node_status_list,
            "node_states": node_states_map,
            "dag_hash": snapshot.dag_hash if snapshot else None,
            "input_files": snapshot.input_files if snapshot else None,
            "workflow": snapshot.workflow if snapshot else None,
        }
        return JSONResponse(status_code=200, content=payload)

    # Not running — load from persisted snapshot
    try:
        snapshot = await _get_workspace_snapshot(
            task_run_repository,
            task_id,
            auth_ctx.workspace_id,
        )
    except Exception:
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    if snapshot is None:
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    node_summary = snapshot.node_summary or {}
    persisted_node_states: dict[str, NodeState] = {}
    if snapshot.workflow:
        try:
            if event_store.get_events(task_id):
                persisted_workflow = WorkflowDefinition.model_validate(snapshot.workflow)
                persisted_node_states = _reconstruct_node_states(
                    task_id,
                    persisted_workflow,
                    event_store,
                )
        except Exception as exc:
            logger.warning(
                "Failed to reconstruct persisted node states for %s error_type=%s",
                task_id,
                type(exc).__name__,
            )

    persisted_node_status = [
        {
            "node_id": state.node_id,
            "node_type": state.node_type,
            "status": state.status.value,
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
            "error": _serialize_node_error(state.error),
            "progress": state.progress,
        }
        for state in persisted_node_states.values()
    ]
    persisted_node_states_map = {item["node_id"]: item for item in persisted_node_status}
    if persisted_node_states:
        total_nodes = len(persisted_node_states)
        completed_nodes = sum(
            1 for state in persisted_node_states.values() if state.status == NodeStatus.COMPLETED
        )
        failed_nodes = sum(
            1 for state in persisted_node_states.values() if state.status == NodeStatus.FAILED
        )
        pending_nodes = sum(
            1 for state in persisted_node_states.values() if state.status == NodeStatus.PENDING
        )
        skipped_nodes = sum(
            1 for state in persisted_node_states.values() if state.status == NodeStatus.SKIPPED
        )
    else:
        total_nodes = sum(node_summary.values()) if node_summary else 0
        completed_nodes = node_summary.get("completed", 0)
        failed_nodes = node_summary.get("failed", 0)
        pending_nodes = 0
        skipped_nodes = node_summary.get("skipped", 0)
    payload = {
        "task_id": task_id,
        "run_name": snapshot.run_name,
        "status": snapshot.status or "unknown",
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        "started_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "completed_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
        "progress": {
            "total_nodes": total_nodes,
            "completed_nodes": completed_nodes,
            "failed_nodes": failed_nodes,
            "pending_nodes": pending_nodes,
            "skipped_nodes": skipped_nodes,
            "current_node": None,
            "percentage": 100 if snapshot.status in ("completed", "failed") else 0,
        },
        "node_status": persisted_node_status,
        "node_states": persisted_node_states_map,
        "dag_hash": snapshot.dag_hash,
        "input_files": snapshot.input_files,
        "workflow": snapshot.workflow,
    }

    if snapshot.error:
        payload["error"] = snapshot.error
    if snapshot.result_preview:
        payload["result_preview"] = snapshot.result_preview

    return JSONResponse(status_code=200, content=payload)


@router.get("/tasks/{task_id}/results", response_model=None)
async def get_task_results(
    request: Request,
    task_id: str,
    auth_ctx: RunViewContext,
) -> JSONResponse:
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    task_run_repository = get_task_run_repository()

    ctx = running_tasks.get(task_id)

    if ctx is not None:
        if not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        # Running task — read from EventStore.compute_state()
        try:
            state = event_store.compute_state(ctx.run_id)
        except Exception:
            state = {}

        # Derive results from nodes connected to end node
        end_node = next((n for n in ctx.workflow.nodes if n.type == "end/final"), None)
        upstream_of_end: set[str] = set()
        if end_node is not None:
            upstream_of_end = {
                c.source for c in ctx.workflow.connections if c.target == end_node.id
            }
        results = []
        for node_id in upstream_of_end:
            output = state.get(node_id)
            if output is not None:
                results.append(_build_result_from_node_output(output, node_id, task_id))

        if not results:
            return error_response(409, "TASK_NOT_COMPLETED", "任務尚未完成，目前狀態：running")

        return build_results_response(
            task_id=task_id,
            status="completed",
            results=[ensure_result_fields(r) for r in results],
        )

    # Not running — fall back to persisted snapshot
    try:
        snapshot = await _get_workspace_snapshot(
            task_run_repository,
            task_id,
            auth_ctx.workspace_id,
        )
        snapshot_status = snapshot.status if snapshot is not None else None
        snapshot_duration_ms = snapshot.duration_ms if snapshot is not None else None
        snapshot_results = snapshot.results if snapshot is not None else None
        snapshot_exists = snapshot is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load persisted results: task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return task_state_unavailable_response(task_id)

    if not snapshot_exists:
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    resolved_status = snapshot_status or "unknown"
    if not is_results_ready_status(resolved_status):
        return error_response(
            409,
            "TASK_NOT_COMPLETED",
            f"任務尚未完成，目前狀態：{resolved_status}",
        )

    normalized_snapshot_results = snapshot_results if isinstance(snapshot_results, list) else []
    results = [
        ensure_result_fields(item, fallback_duration_ms=snapshot_duration_ms)
        for item in normalized_snapshot_results
        if isinstance(item, dict)
    ]
    return build_results_response(
        task_id=task_id,
        status=resolved_status,
        results=results,
    )


@router.get("/tasks/{task_id}/results/{result_id}/download", response_model=None)
async def download_result(
    request: Request,
    task_id: str,
    result_id: str,
    auth_ctx: RunViewContext,
) -> JSONResponse | Response:
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    task_run_repository = get_task_run_repository()
    if not await _task_visible_in_workspace(
        task_id=task_id,
        running_tasks=running_tasks,
        repository=task_run_repository,
        workspace_id=auth_ctx.workspace_id,
    ):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
    orchestrator: TaskOrchestrator = request.app.state.task_orchestrator
    context = orchestrator.get_task(task_id)
    context_status = extract_context_status(context) or "unknown"

    candidates: list[TaskResult]
    if context is not None and is_results_ready_status(context_status):
        candidates = collect_results_from_context(
            context.task_id,
            context.result,
            context.node_states,
        )
    else:
        try:
            snapshot = await _get_workspace_snapshot(
                task_run_repository,
                task_id,
                auth_ctx.workspace_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load task snapshot for download: task_id=%s error_type=%s",
                task_id,
                type(exc).__name__,
            )
            return task_state_unavailable_response(task_id)

        if snapshot is None:
            if context is not None:
                return error_response(
                    409,
                    "TASK_NOT_COMPLETED",
                    f"任務尚未完成，目前狀態：{context_status}",
                )
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

        snapshot_status_value = getattr(snapshot, "status", None)
        snapshot_status = (
            snapshot_status_value if isinstance(snapshot_status_value, str) else context_status
        )
        snapshot_status = snapshot_status or "unknown"
        if not is_results_ready_status(snapshot_status):
            return error_response(
                409,
                "TASK_NOT_COMPLETED",
                f"任務尚未完成，目前狀態：{snapshot_status}",
            )

        snapshot_results_value = getattr(snapshot, "results", None)
        snapshot_results = (
            snapshot_results_value if isinstance(snapshot_results_value, list) else []
        )
        candidates = collect_results_from_snapshot(task_id, snapshot_results)

    result = next((item for item in candidates if item.result_id == result_id), None)
    if result is None:
        return error_response(404, "RESULT_NOT_FOUND", f"找不到結果：{result_id}")

    settings = get_settings()
    try:
        ensure_path_within_root(result.storage_path, settings.storage_root)
    except ValueError:
        return error_response(403, "ACCESS_DENIED", "存取被拒絕")

    result_path = Path(result.storage_path)
    if not result_path.exists() or not result_path.is_file():
        return error_response(404, "RESULT_NOT_FOUND", f"找不到結果檔案：{result_id}")

    from urllib.parse import quote

    safe_name = quote(result.filename, safe="")
    try:
        content = result_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "Failed to read result file: task_id=%s result_id=%s error_type=%s",
            task_id,
            result_id,
            type(exc).__name__,
        )
        return error_response(500, "RESULT_READ_FAILED", f"結果檔案讀取失敗：{result_id}")
    return Response(
        content=content,
        media_type=result.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


# ---------------------------------------------------------------------------
# Per-node result helpers
# ---------------------------------------------------------------------------


def _serialize_node_error(error: object) -> str | dict[str, object] | None:
    """Serialize node error for JSON response."""
    if error is None:
        return None
    if isinstance(error, str):
        return error
    # NodeFailureInfo or similar model
    if isinstance(error, ModelDumpable):
        dumped = error.model_dump()
        return dumped if isinstance(dumped, dict) else str(dumped)
    return str(error)


def _serialize_node_output(
    node_id: str,
    node_type: str,
    output: object,
    task_id: str,
) -> dict[str, object]:
    """Serialize a NodeState.output into a JSON-safe dict."""
    from app.models.execution import NodeOutput
    from app.models.inputs import ImageInput, TextInput

    if output is None:
        return {"output_type": None, "data": None}

    # Output nodes produce TaskResult
    if isinstance(output, TaskResult):
        return {
            "output_type": "formatted_text",
            "data": {
                "result_id": output.result_id,
                "format": output.format,
                "filename": output.filename,
                "content_type": output.content_type,
                "content": output.content,
                "download_url": output.download_url,
                "metadata": {
                    "processing_time_ms": output.metadata.processing_time_ms,
                    "page_count": output.metadata.page_count,
                    "char_count": output.metadata.char_count,
                    "word_count": output.metadata.word_count,
                },
            },
        }

    # Engine/processor nodes produce NodeOutput
    if isinstance(output, NodeOutput):
        data: dict[str, object] = {
            "text": output.text,
            "metadata": output.metadata,
        }
        result: dict[str, object] = {
            "output_type": "node_output",
            "data": data,
        }
        # Include binary refs (image output, cropped regions, etc.)
        if output.binary:
            data["binary"] = [
                {
                    "ref": b.ref,
                    "mime_type": b.mime_type,
                    "size_bytes": b.size_bytes,
                    "dimensions": b.dimensions,
                }
                for b in output.binary
            ]
            # If this is an image processor, provide image URL
            if output.binary and output.binary[0].ref:
                data["image_url"] = f"/api/tasks/{task_id}/nodes/{node_id}/image"
        # Include structured data (layout elements, OCR blocks, etc.)
        if output.structured:
            data["structured"] = output.structured
        return result

    # Input nodes produce TextInput
    if isinstance(output, TextInput):
        return {
            "output_type": "text_input",
            "data": {
                "id": output.id,
                "source": output.source.model_dump() if output.source else None,
                "content": output.content.raw,
                "char_count": output.content.char_count,
                "line_count": output.content.line_count,
            },
        }

    # Input nodes produce ImageInput
    if isinstance(output, ImageInput):
        return {
            "output_type": "image_input",
            "data": {
                "id": output.id,
                "source": output.source.model_dump() if output.source else None,
                "width": output.data.width if output.data else None,
                "height": output.data.height if output.data else None,
                "format": output.data.format if output.data else None,
                "image_url": f"/api/tasks/{task_id}/nodes/{node_id}/image",
                "size_bytes": output.data.size_bytes if output.data else None,
                "page_info": output.page_info.model_dump() if output.page_info else None,
            },
        }

    # Dict output (e.g., end node summary)
    if isinstance(output, dict):
        return {
            "output_type": "summary",
            "data": output,
        }

    # List output (e.g., batch results)
    if isinstance(output, list):
        return {
            "output_type": "list",
            "data": [_serialize_node_output(node_id, node_type, item, task_id) for item in output],
        }

    # Unknown type -> try to serialize
    if isinstance(output, ModelDumpable):
        dumped = output.model_dump()
        return {
            "output_type": "model",
            "data": dumped if isinstance(dumped, dict) else str(dumped),
        }

    return {
        "output_type": "unknown",
        "data": str(output),
    }


# ---------------------------------------------------------------------------
# Per-node result endpoint
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}/nodes/{node_id}/result", response_model=None)
async def get_node_result(
    request: Request,
    task_id: str,
    node_id: str,
    auth_ctx: RunViewContext,
) -> JSONResponse | Response:
    """Return the execution result for a specific node."""
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    task_run_repository = get_task_run_repository()
    if not await _task_visible_in_workspace(
        task_id=task_id,
        running_tasks=running_tasks,
        repository=task_run_repository,
        workspace_id=auth_ctx.workspace_id,
    ):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    ctx = running_tasks.get(task_id)
    # run_id equals task_id (set during _start_dag_run)
    run_id = ctx.run_id if ctx else task_id

    output, status, error, node_type = _node_output_from_events(run_id, node_id, event_store)
    if status == "pending" and not output:
        return error_response(404, "NODE_NOT_FOUND", f"找不到節點：{node_id}")

    if status not in ("completed", "failed", "skipped"):
        return JSONResponse(
            status_code=200,
            content={
                "node_id": node_id,
                "node_type": node_type,
                "status": status,
                "output_type": None,
                "data": None,
            },
        )

    # Build new-format output for NodeOutput types
    from app.models.execution import NodeOutput as NodeOutputModel

    result_data = _serialize_node_output(node_id, node_type, output, task_id)
    response_content: dict[str, object] = {
        "node_id": node_id,
        "node_type": node_type,
        "status": status,
        "error": error or None,
        **result_data,
    }

    # Include raw NodeOutput for the new frontend format
    if isinstance(output, NodeOutputModel):
        response_content["output"] = output.model_dump(mode="json")

    return JSONResponse(status_code=200, content=response_content)


def _serve_image_file(image_path: Path) -> Response:
    """Read an image/PDF file and return a Response with the correct media type."""
    suffix = image_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    content = image_path.read_bytes()
    headers: dict[str, str] = {"Cache-Control": "private, max-age=300"}
    if media_type == "application/pdf":
        headers["Content-Disposition"] = "inline"
    return Response(
        content=content,
        media_type=media_type,
        headers=headers,
    )


@router.get("/tasks/{task_id}/nodes/{node_id}/image", response_model=None)
async def get_node_image(
    request: Request,
    task_id: str,
    node_id: str,
    auth_ctx: RunViewContext,
    index: int = 0,
) -> JSONResponse | Response:
    """Serve the processed image output of a processor node.

    When ``index`` is provided, serve ``binary[index]`` instead of
    ``binary[0]``. Inline base64 ``data`` takes precedence over a temp-file
    ``ref`` so that multi-image enhancement/rotation outputs are servable
    even when they carry no file reference. For a bbox-only Layout Detection
    result, the endpoint resolves the source image from the node's latest
    upstream execution event.
    """
    from app.models.execution import NodeOutput
    from app.models.inputs import ImageInput

    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    task_run_repository = get_task_run_repository()
    if not await _task_visible_in_workspace(
        task_id=task_id,
        running_tasks=running_tasks,
        repository=task_run_repository,
        workspace_id=auth_ctx.workspace_id,
    ):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    ctx = running_tasks.get(task_id)
    run_id = ctx.run_id if ctx else task_id

    output, _status, _error, _node_type = _node_output_from_events(run_id, node_id, event_store)

    if (
        _node_type == "processor/layout_detection"
        and isinstance(output, NodeOutput)
        and not output.binary
    ):
        source_output = _upstream_output_from_events(run_id, node_id, event_store)
        if source_output is not None:
            output = source_output
    # Serve input image files (ImageInput from input nodes)
    if isinstance(output, ImageInput):
        image_path = Path(output.data.file_path).resolve()
        settings = get_settings()
        try:
            ensure_path_within_roots(image_path, [settings.storage_root, "/tmp"])
        except ValueError:
            return error_response(403, "ACCESS_DENIED", "存取被拒絕")

        if not image_path.exists() or not image_path.is_file():
            return error_response(404, "IMAGE_NOT_FOUND", "圖像檔案不存在")

        try:
            return _serve_image_file(image_path)
        except OSError as exc:
            logger.warning(
                "Failed to read input image: task_id=%s node_id=%s error_type=%s",
                task_id,
                node_id,
                type(exc).__name__,
            )
            return error_response(500, "IMAGE_READ_FAILED", "圖像檔案讀取失敗")

    # Serve image from NodeOutput binary
    if isinstance(output, NodeOutput):
        if not output.binary:
            return error_response(404, "NO_IMAGE", "此節點無圖像輸出")

        if index < 0 or index >= len(output.binary):
            return error_response(
                404,
                "INDEX_OUT_OF_RANGE",
                f"index {index} out of range for binary list of length {len(output.binary)}",
            )

        entry = output.binary[index]

        if entry.data:
            try:
                raw = base64.b64decode(entry.data)
            except ValueError as exc:
                logger.warning(
                    "Failed to decode inline image data: task_id=%s node_id=%s index=%d "
                    "error_type=%s",
                    task_id,
                    node_id,
                    index,
                    type(exc).__name__,
                )
                return error_response(500, "IMAGE_DECODE_FAILED", "圖像數據解碼失敗")
            media_type = entry.mime_type or "application/octet-stream"
            headers: dict[str, str] = {"Cache-Control": "private, max-age=300"}
            if media_type == "application/pdf":
                headers["Content-Disposition"] = "inline"
            return Response(content=raw, media_type=media_type, headers=headers)

        if entry.ref:
            image_path = Path(entry.ref).resolve()
            settings = get_settings()
            try:
                ensure_path_within_roots(image_path, [settings.storage_root, "/tmp"])
            except ValueError:
                return error_response(403, "ACCESS_DENIED", "存取被拒絕")
            if image_path.exists():
                try:
                    return _serve_image_file(image_path)
                except OSError as exc:
                    logger.warning(
                        "Failed to read node image: task_id=%s node_id=%s index=%d error_type=%s",
                        task_id,
                        node_id,
                        index,
                        type(exc).__name__,
                    )
                    return error_response(500, "IMAGE_READ_FAILED", "圖像檔案讀取失敗")

        return error_response(
            404,
            "NO_IMAGE",
            f"binary[{index}] has neither inline data nor a resolvable ref",
        )

    return error_response(404, "NO_IMAGE", "此節點無圖像輸出")


@router.post("/tasks/{task_id}/retry", response_model=None)
async def retry_workflow(
    request: Request,
    task_id: str,
    auth_ctx: RunCancelContext,
) -> JSONResponse:
    """Workflow-level retry: re-execute all failed nodes and their downstream."""
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    dag_scheduler: DAGScheduler = request.app.state.dag_scheduler
    engine_client: EngineClient = request.app.state.engine_client

    # Check if already running
    ctx = running_tasks.get(task_id)
    if ctx is not None and not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
    if ctx is not None and ctx.asyncio_task and not ctx.asyncio_task.done():
        return error_response(409, "ALREADY_RUNNING", "任務正在執行中，無法重試")

    # Find the task context
    if ctx is not None:
        workflow = ctx.workflow
        run_id = ctx.run_id
    else:
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    # Find all failed nodes from event store
    events = event_store.get_events(run_id)
    failed_nodes: set[str] = set()
    for e in events:
        if e.event_type == "failed":
            failed_nodes.add(e.node_id)

    if not failed_nodes:
        return error_response(409, "NO_FAILED_NODES", "沒有失敗的節點可重試")

    # Compute downstream for all failed nodes
    all_rerun_nodes: set[str] = set()
    for node_id in failed_nodes:
        downstream = _find_downstream_nodes(workflow, node_id)
        all_rerun_nodes.update(downstream)
    all_rerun_nodes.update(failed_nodes)

    # Clear events for rerun nodes
    event_store.delete_events_for_nodes(run_id, all_rerun_nodes)

    # Kick off partial DAG run
    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow,
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        event_store=event_store,
        running_tasks=running_tasks,
        created_at=datetime.now(timezone.utc),
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        start_nodes=failed_nodes,
        workspace_id=auth_ctx.workspace_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "status": "pending",
            "failed_nodes": sorted(failed_nodes),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.post("/tasks/{task_id}/nodes/{node_id}/retry", response_model=None)
async def retry_task_node(
    request: Request,
    task_id: str,
    node_id: str,
    auth_ctx: RunCancelContext,
) -> JSONResponse:

    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    dag_scheduler: DAGScheduler = request.app.state.dag_scheduler
    engine_client: EngineClient = request.app.state.engine_client
    task_run_repository = get_task_run_repository()

    # Find the task — check running_tasks first, then snapshot
    ctx = running_tasks.get(task_id)
    workflow: WorkflowDefinition | None = None
    run_id: str | None = None

    if ctx is not None:
        if not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        workflow = ctx.workflow
        run_id = ctx.run_id
    else:
        try:
            snapshot = await _get_workspace_snapshot(
                task_run_repository,
                task_id,
                auth_ctx.workspace_id,
            )
        except Exception:
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        if snapshot is None:
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        # Need to get the workflow from snapshot — not stored directly
        # Check if task is in a terminal state
        if snapshot.status not in ("failed",):
            return error_response(
                409, "RETRY_NOT_ALLOWED", f"任務狀態不允許重試：{snapshot.status}"
            )
        # For snapshot-only tasks, we can't retry without the workflow definition
        return error_response(409, "RETRY_NOT_AVAILABLE", "此任務不支援重試（缺少 workflow 定義）")

    # Verify the target node exists
    target = workflow.get_node(node_id)
    if target is None:
        return error_response(404, "NODE_NOT_FOUND", f"找不到節點：{node_id}")

    # Find the target node and all downstream nodes
    downstream = _find_downstream_nodes(workflow, node_id)
    nodes_to_clear = downstream | {node_id}

    # Clear failed/skipped events for target and downstream nodes
    event_store.delete_events_for_nodes(run_id, nodes_to_clear)

    # Kick off DAGScheduler.run() with same run_id to resume
    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow,
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        event_store=event_store,
        running_tasks=running_tasks,
        created_at=datetime.now(timezone.utc),
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        workspace_id=auth_ctx.workspace_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "node_id": node_id,
            "status": "pending",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.post("/tasks/{task_id}/nodes/{node_id}/rerun", response_model=None)
async def rerun_task_node(
    request: Request,
    task_id: str,
    node_id: str,
    auth_ctx: RunCancelContext,
) -> JSONResponse:
    """Node-level rerun: re-execute target node and all downstream nodes."""
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store
    dag_scheduler: DAGScheduler = request.app.state.dag_scheduler
    engine_client: EngineClient = request.app.state.engine_client

    # Check if already running
    ctx = running_tasks.get(task_id)
    if ctx is not None and not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
    if ctx is not None and ctx.asyncio_task and not ctx.asyncio_task.done():
        return error_response(409, "ALREADY_RUNNING", "任務正在執行中，無法重跑")

    # Find the task context
    if ctx is not None:
        workflow = ctx.workflow
        run_id = ctx.run_id
    else:
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    # Verify the target node exists
    target = workflow.get_node(node_id)
    if target is None:
        return error_response(404, "NODE_NOT_FOUND", f"找不到節點：{node_id}")

    # Find the target node and all downstream nodes
    downstream = _find_downstream_nodes(workflow, node_id)
    rerun_nodes = downstream | {node_id}

    # Clear events for target and downstream nodes
    event_store.delete_events_for_nodes(run_id, rerun_nodes)

    # Kick off partial DAG run starting from target node
    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow,
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        event_store=event_store,
        running_tasks=running_tasks,
        created_at=datetime.now(timezone.utc),
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        start_nodes={node_id},
        workspace_id=auth_ctx.workspace_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "node_id": node_id,
            "status": "pending",
            "rerun_nodes": sorted(rerun_nodes),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.post("/tasks/{task_id}/reset", response_model=None)
async def reset_task(
    request: Request,
    task_id: str,
    auth_ctx: RunCancelContext,
) -> JSONResponse:
    """Clear task context (snapshot) and return to idle state."""
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    event_store: EventStore = request.app.state.event_store

    ctx = running_tasks.get(task_id)

    if ctx is not None:
        if not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        # Cancel background task if still running
        if ctx.asyncio_task and not ctx.asyncio_task.done():
            ctx.asyncio_task.cancel()
        running_tasks.pop(task_id, None)
        event_store.delete_events(task_id)
    else:
        task_run_repository = get_task_run_repository()
        snapshot = await _get_workspace_snapshot(
            task_run_repository,
            task_id,
            auth_ctx.workspace_id,
        )
        if snapshot is None:
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    return JSONResponse(
        status_code=200,
        content={
            "task_id": task_id,
            "status": "idle",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.delete("/tasks/{task_id}", response_model=None)
async def cancel_task(
    request: Request,
    task_id: str,
    auth_ctx: RunCancelContext,
) -> JSONResponse:
    running_tasks: dict[str, RunningTaskContext] = request.app.state.running_tasks
    task_run_repository = get_task_run_repository()

    ctx = running_tasks.get(task_id)
    if ctx is not None and not _matches_workspace(ctx.workspace_id, auth_ctx.workspace_id):
        return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")

    if ctx is None:
        # Not running — check if it exists in snapshots
        try:
            snapshot = await _get_workspace_snapshot(
                task_run_repository,
                task_id,
                auth_ctx.workspace_id,
            )
        except Exception:
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        if snapshot is None:
            return error_response(404, "TASK_NOT_FOUND", f"找不到任務：{task_id}")
        return error_response(409, "CANCEL_NOT_ALLOWED", f"任務已完成，無法取消：{snapshot.status}")

    # Set cancel flag — scheduler will pick it up on next iteration
    ctx.cancel_requested = True

    # Update snapshot to cancelled immediately
    try:
        await task_run_repository.upsert_snapshot(
            task_id=task_id,
            status="cancelled",
            workflow_id=None,
            workflow_name=None,
            run_name=None,
            workspace_id=auth_ctx.workspace_id,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            updated_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning(
            "Failed to update snapshot for cancel: %s error_type=%s",
            task_id,
            type(exc).__name__,
        )
    else:
        if FeatureFlags.is_queue_mode():
            from app.worker import celery_app

            celery_app.control.revoke(task_id, terminate=False)

    return JSONResponse(
        status_code=200,
        content={
            "task_id": task_id,
            "status": "cancelled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
