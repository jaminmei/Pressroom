from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Protocol

import httpx
import sqlalchemy as sa
from celery import Celery
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.engine_timeout import get_engine_timeout_config
from app.db.session import SessionLocal
from app.errors import RETRYABLE_ENGINE_ERRORS, EngineError, ErrorCode
from app.models.execution import ExecutionEvent, NodeOutput
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition
from app.providers.auth import AuthResolver
from app.providers.db import get_db_path
from app.providers.encryption import get_fernet
from app.providers.plugin_loader import bootstrap_provider_registry
from app.providers.store import ProviderStore
from app.services.dag_scheduler import DAGScheduler
from app.services.durable_workflow_execution import execute_workflow_sync
from app.services.engine_client import EngineClient
from app.services.event_store import EventStore
from app.services.final_output_serializer import build_final_output_snapshot_entries
from app.services.node_registry import NodeRegistryService
from app.storage.local import get_storage

if TYPE_CHECKING:
    from app.repositories.evaluation_repository import EvaluationRepository
    from app.services.dag_scheduler import DAGRunResult, NodeExecutor

logger = logging.getLogger(__name__)

MAX_INPUT_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

EXECUTE_WORKFLOW_TASK_NAME = "execute_workflow_task"
EXECUTE_EVALUATION_DOCUMENT_TASK_NAME = "execute_evaluation_document"
WORKER_SMOKE_TASK_NAME = "worker_smoke_task"
RESULT_PREVIEW_MAX_CHARS = 500
QUEUE_TASK_MAX_RETRIES = 3
QUEUE_TASK_DEFAULT_RETRY_DELAY_SECONDS = 5
QUEUE_TASK_RETRY_BACKOFF_MAX_SECONDS = 60
FALLBACK_HEALTHCHECK_TIMEOUT_SECONDS = 5


class _RetryRequest(Protocol):
    retries: int


class RetryCapableTask(Protocol):
    request: _RetryRequest
    max_retries: int

    def retry(self, *, exc: Exception, countdown: int | None = None) -> NoReturn: ...


def register_worker_tasks(celery_app: Celery) -> None:
    if EXECUTE_WORKFLOW_TASK_NAME in celery_app.tasks:
        return

    @celery_app.task(
        name=EXECUTE_WORKFLOW_TASK_NAME,
        bind=True,
        max_retries=QUEUE_TASK_MAX_RETRIES,
        default_retry_delay=QUEUE_TASK_DEFAULT_RETRY_DELAY_SECONDS,
        retry_backoff=True,
        retry_backoff_max=QUEUE_TASK_RETRY_BACKOFF_MAX_SECONDS,
        retry_jitter=True,
        acks_late=True,
        reject_on_worker_lost=True,
    )
    def execute_workflow_task(
        task_self: RetryCapableTask,
        task_run_id: str,
        workflow_def: dict[str, object],
        input_data: dict[str, object],
        context_data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        engine_node = _resolve_engine_node(workflow_def)
        node_id = str(engine_node.get("id", "engine_1"))
        node_type = str(engine_node.get("type", "engine/ocr"))
        retry_count = int(getattr(getattr(task_self, "request", object()), "retries", 0))
        max_retries = int(getattr(task_self, "max_retries", QUEUE_TASK_MAX_RETRIES))
        try:
            return execute_workflow_task_sync(
                task_run_id,
                workflow_def,
                input_data,
                context_data=context_data,
                enable_task_retry=True,
                retry_count=retry_count,
                max_retries=max_retries,
            )
        except EngineError as error:
            _retry_or_raise_engine_error(
                task_self=task_self,
                error=error,
                task_run_id=task_run_id,
                node_id=node_id,
                node_type=node_type,
            )
            raise

    @celery_app.task(
        name=EXECUTE_EVALUATION_DOCUMENT_TASK_NAME,
        bind=True,
        max_retries=QUEUE_TASK_MAX_RETRIES,
        default_retry_delay=QUEUE_TASK_DEFAULT_RETRY_DELAY_SECONDS,
        retry_backoff=True,
        retry_backoff_max=QUEUE_TASK_RETRY_BACKOFF_MAX_SECONDS,
        retry_jitter=True,
        acks_late=True,
        reject_on_worker_lost=True,
    )
    def execute_evaluation_document(
        task_self: RetryCapableTask,
        result_id: str,
    ) -> dict[str, object]:
        retry_count = int(getattr(getattr(task_self, "request", object()), "retries", 0))
        max_retries = int(getattr(task_self, "max_retries", QUEUE_TASK_MAX_RETRIES))
        try:
            return execute_evaluation_document_sync(
                result_id,
                enable_task_retry=True,
                retry_count=retry_count,
                max_retries=max_retries,
            )
        except EngineError as error:
            _retry_or_raise_engine_error(
                task_self=task_self,
                error=error,
                task_run_id=result_id,
                node_id="evaluation_document",
                node_type="engine/evaluation",
            )
            raise

    @celery_app.task(name=WORKER_SMOKE_TASK_NAME)
    def worker_smoke_task(payload: str) -> dict[str, str]:
        return {"echo": payload}


def execute_workflow_task_sync(
    task_run_id: str,
    workflow_def: dict[str, object],
    input_data: dict[str, object],
    context_data: dict[str, object] | None = None,
    *,
    enable_task_retry: bool = False,
    retry_count: int = 0,
    max_retries: int = QUEUE_TASK_MAX_RETRIES,
) -> dict[str, object]:
    bootstrap_provider_registry()
    context_data = context_data or {}
    if _optional_str(context_data.get("workspace_id")) is not None:
        return _execute_full_workflow_task_sync(
            task_run_id=task_run_id,
            workflow_def=workflow_def,
            input_data=input_data,
            context_data=context_data,
        )

    started_at = _now()
    workspace_id = _optional_str(context_data.get("workspace_id"))
    _validate_input_workspace(input_data, workspace_id)
    engine_node = _resolve_engine_node(workflow_def)
    engine_node_id = str(engine_node.get("id", "engine_1"))
    engine_type = _parse_engine_type(str(engine_node.get("type", "engine/ocr")))
    node_type = f"engine/{engine_type}"
    engine_config = engine_node.get("config", {})
    raw_config = engine_config if isinstance(engine_config, dict) else {}
    primary_config = _sanitize_engine_config(raw_config)
    fallback_engine, fallback_config = _resolve_fallback_settings(
        config=raw_config,
        primary_engine=engine_type,
    )
    input_file_path: str | None = None

    with SessionLocal() as session:
        _validate_job_scope(session, context_data, workspace_id)
        _upsert_task_run(
            session,
            task_run_id=task_run_id,
            status="running",
            workflow_id=_optional_str(context_data.get("workflow_id")),
            workflow_name=_optional_str(context_data.get("workflow_name")),
            run_name=_optional_str(context_data.get("run_name")),
            source=_optional_str(context_data.get("source")) or "manual",
            evaluation_run_id=_optional_str(context_data.get("evaluation_run_id")),
            workspace_id=workspace_id,
            error=None,
            updated_at=started_at,
        )
        _upsert_node_run(
            session,
            task_run_id=task_run_id,
            node_id=engine_node_id,
            node_type=node_type,
            status="running",
            started_at=started_at,
            updated_at=started_at,
        )
        _append_task_event(
            session,
            task_run_id=task_run_id,
            event_type="task_running",
            payload={"task_id": task_run_id, "status": "running"},
            created_at=started_at,
        )
        _append_task_event(
            session,
            task_run_id=task_run_id,
            event_type="node_started",
            payload={"task_id": task_run_id, "node_id": engine_node_id, "node_type": node_type},
            created_at=started_at,
        )
        session.commit()

    try:
        input_file_path = _resolve_input_file_path(workflow_def, input_data, engine_node_id)
        if workspace_id is not None:
            response_body = _call_engine_sync(
                engine_type=engine_type,
                input_file_path=input_file_path,
                config=primary_config,
                workspace_id=workspace_id,
            )
        else:
            response_body = _call_engine_sync(
                engine_type=engine_type,
                input_file_path=input_file_path,
                config=primary_config,
            )
        completed_at = _now()
        duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
        result_preview = _build_result_preview(response_body)

        with SessionLocal() as session:
            _upsert_node_run(
                session,
                task_run_id=task_run_id,
                node_id=engine_node_id,
                node_type=node_type,
                status="completed",
                duration_ms=duration_ms,
                completed_at=completed_at,
                updated_at=completed_at,
            )
            _append_task_event(
                session,
                task_run_id=task_run_id,
                event_type="node_completed",
                payload={"task_id": task_run_id, "node_id": engine_node_id, "node_type": node_type},
                created_at=completed_at,
            )
            _upsert_task_run(
                session,
                task_run_id=task_run_id,
                status="completed",
                workflow_id=_optional_str(context_data.get("workflow_id")),
                workflow_name=_optional_str(context_data.get("workflow_name")),
                run_name=_optional_str(context_data.get("run_name")),
                source=_optional_str(context_data.get("source")) or "manual",
                evaluation_run_id=_optional_str(context_data.get("evaluation_run_id")),
                workspace_id=workspace_id,
                duration_ms=duration_ms,
                completed_at=completed_at,
                node_summary={"total": 1, "completed": 1, "failed": 0},
                result_preview=result_preview,
                error=None,
                updated_at=completed_at,
            )
            _append_task_event(
                session,
                task_run_id=task_run_id,
                event_type="task_completed",
                payload={
                    "task_id": task_run_id,
                    "status": "completed",
                    "duration_seconds": duration_ms // 1000,
                },
                created_at=completed_at,
            )
            session.commit()

        return {"task_run_id": task_run_id, "status": "completed", "engine_type": engine_type}
    except Exception as exc:  # noqa: BLE001
        normalized_error = _normalize_engine_error(
            exc,
            engine_type=engine_type,
            node_id=engine_node_id,
        )
        is_retryable = _is_retryable_engine_error(normalized_error)
        if enable_task_retry and is_retryable and retry_count < max_retries:
            raise normalized_error from exc

        fallback_response: dict[str, object] | None = None
        fallback_error: EngineError | None = None
        should_attempt_fallback = is_retryable and (
            not enable_task_retry or retry_count >= max_retries
        )
        if should_attempt_fallback and input_file_path is not None:
            fallback_response, fallback_error = _try_fallback_engine_sync(
                task_run_id=task_run_id,
                node_id=engine_node_id,
                node_type=node_type,
                input_file_path=input_file_path,
                primary_engine=engine_type,
                fallback_engine=fallback_engine,
                fallback_config=fallback_config,
                primary_error=normalized_error,
                workspace_id=workspace_id,
            )
        if fallback_response is not None and fallback_engine is not None:
            completed_at = _now()
            duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
            result_preview = _build_result_preview(fallback_response)

            with SessionLocal() as session:
                _upsert_node_run(
                    session,
                    task_run_id=task_run_id,
                    node_id=engine_node_id,
                    node_type=node_type,
                    status="completed",
                    duration_ms=duration_ms,
                    error=None,
                    completed_at=completed_at,
                    updated_at=completed_at,
                )
                _append_task_event(
                    session,
                    task_run_id=task_run_id,
                    event_type="node_completed",
                    payload={
                        "task_id": task_run_id,
                        "node_id": engine_node_id,
                        "node_type": node_type,
                        "timestamp": completed_at.isoformat(),
                        "meta": {
                            "fallback_from": f"engine/{engine_type}",
                            "fallback_engine": f"engine/{fallback_engine}",
                            "fallback_reason": normalized_error.error_code.value,
                        },
                    },
                    created_at=completed_at,
                )
                _upsert_task_run(
                    session,
                    task_run_id=task_run_id,
                    status="completed",
                    workflow_id=_optional_str(context_data.get("workflow_id")),
                    workflow_name=_optional_str(context_data.get("workflow_name")),
                    run_name=_optional_str(context_data.get("run_name")),
                    source=_optional_str(context_data.get("source")) or "manual",
                    evaluation_run_id=_optional_str(context_data.get("evaluation_run_id")),
                    workspace_id=workspace_id,
                    duration_ms=duration_ms,
                    completed_at=completed_at,
                    node_summary={"total": 1, "completed": 1, "failed": 0},
                    result_preview=result_preview,
                    error=None,
                    updated_at=completed_at,
                )
                _append_task_event(
                    session,
                    task_run_id=task_run_id,
                    event_type="task_completed",
                    payload={
                        "task_id": task_run_id,
                        "status": "completed",
                        "duration_seconds": duration_ms // 1000,
                    },
                    created_at=completed_at,
                )
                session.commit()

            return {
                "task_run_id": task_run_id,
                "status": "completed",
                "engine_type": fallback_engine,
                "fallback_from": engine_type,
                "fallback_reason": normalized_error.error_code.value,
            }

        final_error: EngineError = fallback_error or normalized_error

        failed_at = _now()
        duration_ms = max(int((failed_at - started_at).total_seconds() * 1000), 0)
        error_message = str(final_error)
        error_code = final_error.error_code.value
        error_details = final_error.details if isinstance(final_error.details, dict) else None

        with SessionLocal() as session:
            _upsert_node_run(
                session,
                task_run_id=task_run_id,
                node_id=engine_node_id,
                node_type=node_type,
                status="failed",
                duration_ms=duration_ms,
                error=error_message,
                completed_at=failed_at,
                updated_at=failed_at,
            )
            _append_task_event(
                session,
                task_run_id=task_run_id,
                event_type="node_failed",
                payload={
                    "task_id": task_run_id,
                    "node_id": engine_node_id,
                    "node_type": node_type,
                    "error_code": error_code,
                    "error": error_message,
                    "details": error_details,
                },
                created_at=failed_at,
            )
            _upsert_task_run(
                session,
                task_run_id=task_run_id,
                status="failed",
                workflow_id=_optional_str(context_data.get("workflow_id")),
                workflow_name=_optional_str(context_data.get("workflow_name")),
                run_name=_optional_str(context_data.get("run_name")),
                source=_optional_str(context_data.get("source")) or "manual",
                evaluation_run_id=_optional_str(context_data.get("evaluation_run_id")),
                workspace_id=workspace_id,
                duration_ms=duration_ms,
                completed_at=failed_at,
                node_summary={"total": 1, "completed": 0, "failed": 1},
                error=error_message,
                updated_at=failed_at,
            )
            _append_task_event(
                session,
                task_run_id=task_run_id,
                event_type="task_failed",
                payload={
                    "task_id": task_run_id,
                    "status": "failed",
                    "error_code": error_code,
                    "error": error_message,
                },
                created_at=failed_at,
            )
            session.commit()

        raise final_error from exc


def execute_evaluation_document_sync(
    result_id: str,
    *,
    enable_task_retry: bool = False,
    retry_count: int = 0,
    max_retries: int = QUEUE_TASK_MAX_RETRIES,
    evaluation_repository: "EvaluationRepository | None" = None,
    node_executor: "NodeExecutor | None" = None,
) -> dict[str, object]:
    """Execute one evaluation result and reconcile its run.

    Loads the durable snapshot from PostgreSQL, takes a per-result advisory
    lock (PostgreSQL only), no-ops on terminal results, runs the workflow
    engine call with 3-attempt EngineError retry, and atomically finalizes
    the result and run under a run-row lock with sticky cancellation.
    """
    import asyncio

    bootstrap_provider_registry()

    return asyncio.run(
        _execute_evaluation_document_async(
            result_id,
            enable_task_retry=enable_task_retry,
            retry_count=retry_count,
            max_retries=max_retries,
            evaluation_repository=evaluation_repository,
            node_executor=node_executor,
        )
    )


async def _execute_evaluation_document_async(
    result_id: str,
    *,
    enable_task_retry: bool,
    retry_count: int,
    max_retries: int,
    evaluation_repository: "EvaluationRepository | None",
    node_executor: "NodeExecutor | None",
) -> dict[str, object]:

    from app.db.session import AsyncSessionLocal
    from app.db.session import engine as async_engine

    dialect_name = ""
    try:
        raw_engine = async_engine.sync_engine
        if hasattr(raw_engine, "dialect"):
            dialect_name = raw_engine.dialect.name
    except Exception:  # noqa: BLE001
        dialect_name = ""

    lock_session = None
    if dialect_name == "postgresql":
        # Session-level advisory lock: held across the entire execution window
        # (snapshot load → engine call → finalize). Paired with pg_advisory_unlock
        # in the finally clause below. Auto-released if the worker dies.
        lock_session = AsyncSessionLocal()
        await lock_session.execute(
            text("SELECT pg_advisory_lock(hashtext(:rid))"), {"rid": result_id}
        )
        await lock_session.commit()

    try:
        return await _run_evaluation_document_body(
            result_id=result_id,
            enable_task_retry=enable_task_retry,
            retry_count=retry_count,
            max_retries=max_retries,
            evaluation_repository=evaluation_repository,
            node_executor=node_executor,
        )
    finally:
        if lock_session is not None:
            try:
                await lock_session.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:rid))"), {"rid": result_id}
                )
                await lock_session.commit()
            except Exception as exc:  # noqa: BLE001 — do not mask the real result
                logger.warning(
                    "Failed to release advisory lock for evaluation result %s error_type=%s",
                    result_id,
                    type(exc).__name__,
                )
            finally:
                await lock_session.close()


async def _run_evaluation_document_body(
    *,
    result_id: str,
    enable_task_retry: bool,
    retry_count: int,
    max_retries: int,
    evaluation_repository: "EvaluationRepository | None",
    node_executor: "NodeExecutor | None",
) -> dict[str, object]:
    from app.repositories.evaluation_repository import EvaluationRepository
    from app.services.dag_scheduler import DAGScheduler
    from app.services.engine_client import EngineClient
    from app.services.node_registry import NodeRegistryService
    from app.storage.local import get_storage

    repository = evaluation_repository or EvaluationRepository()

    snapshot = await repository.load_result_for_execution(result_id)
    if snapshot is None:
        return {"result_id": result_id, "status": "missing"}
    result_status = str(snapshot.get("result_status") or "")
    if result_status in ("completed", "failed", "skipped"):
        return {
            "result_id": result_id,
            "status": result_status,
            "run_id": snapshot.get("run_id"),
        }

    workflow_snapshot = snapshot.get("workflow_snapshot")
    if not isinstance(workflow_snapshot, dict):
        await repository.finalize_result(
            result_id,
            outcome_status="failed",
            output_content=None,
            output_format=None,
            processing_time_ms=None,
            error="Evaluation run is missing its workflow snapshot",
            task_run_results=None,
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
        return {"result_id": result_id, "status": "failed"}

    workflow = WorkflowDefinition.model_validate(workflow_snapshot)
    workspace_id = str(snapshot.get("workspace_id"))
    document_storage_path = str(snapshot.get("document_storage_path"))
    input_node_id = next(
        (n.id for n in workflow.nodes if n.type.startswith("input/")),
        "input_1",
    )
    input_bindings = {
        input_node_id: TaskInputFile(
            file_path=str(Path(get_settings().storage_root) / document_storage_path),
            filename=str(snapshot.get("document_filename")),
            mime_type=str(snapshot.get("document_mime_type")),
            size_bytes=int(snapshot.get("document_size_bytes") or 0),
            workspace_id=workspace_id,
        )
    }
    task_run_id = str(snapshot.get("task_run_id")) if snapshot.get("task_run_id") else None

    execution_status = await repository.mark_result_running(
        result_id,
        workspace_id=workspace_id,
    )
    if execution_status != "running":
        return {
            "result_id": result_id,
            "status": execution_status or "missing",
            "run_id": snapshot.get("run_id"),
        }

    dag_scheduler = DAGScheduler(
        event_store=_WorkerEventStore(),
        node_registry=NodeRegistryService(),
        storage=get_storage(),
    )
    engine_client = EngineClient(settings=get_settings())
    store = ProviderStore(db_path=get_db_path(), fernet=get_fernet())
    started_at = _now()

    try:
        result = await _run_evaluation_engine_call(
            workflow=workflow,
            task_run_id=task_run_id or result_id,
            input_bindings=input_bindings,
            workspace_id=workspace_id,
            dag_scheduler=dag_scheduler,
            engine_client=engine_client,
            store=store,
            node_executor=node_executor,
        )
    except EngineError as error:
        await engine_client.close()
        if enable_task_retry and _is_retryable_engine_error(error) and retry_count < max_retries:
            raise
        return await _finalize_evaluation_failure(
            repository=repository,
            result_id=result_id,
            task_run_id=task_run_id,
            error=error,
            workflow=workflow,
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 — non-engine error path
        await engine_client.close()
        normalized = _normalize_engine_error(
            exc,
            engine_type="evaluation",
            node_id=str(snapshot.get("document_id") or "evaluation_document"),
        )
        if (
            enable_task_retry
            and _is_retryable_engine_error(normalized)
            and retry_count < max_retries
        ):
            raise normalized from exc
        return await _finalize_evaluation_failure(
            repository=repository,
            result_id=result_id,
            task_run_id=task_run_id,
            error=normalized,
            workflow=workflow,
            started_at=started_at,
        )

    try:
        await engine_client.close()
    except Exception:  # noqa: BLE001
        pass

    return await _finalize_evaluation_success(
        repository=repository,
        result_id=result_id,
        task_run_id=task_run_id,
        workflow=workflow,
        result=result,
        started_at=started_at,
        source_filename=str(snapshot.get("document_filename")),
    )


async def _run_evaluation_engine_call(
    *,
    workflow: WorkflowDefinition,
    task_run_id: str,
    input_bindings: dict[str, TaskInputFile],
    workspace_id: str,
    dag_scheduler: DAGScheduler,
    engine_client: EngineClient,
    store: ProviderStore,
    node_executor: "NodeExecutor | None",
) -> "DAGRunResult":
    from app.services.durable_workflow_execution import (
        DurableWorkflowExecutionService,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        auth_resolver=AuthResolver(fernet=get_fernet()),
        provider_store=store,
    )
    return await service.execute(
        workflow,
        task_id=task_run_id,
        input_bindings=input_bindings,
        workspace_id=workspace_id,
        node_executor=node_executor,
    )


async def _finalize_evaluation_success(
    *,
    repository: "EvaluationRepository",
    result_id: str,
    task_run_id: str | None,
    workflow: WorkflowDefinition,
    result: "DAGRunResult",
    started_at: datetime,
    source_filename: str | None,
) -> dict[str, object]:
    completed_at = _now()
    duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
    snapshot_entries = build_final_output_snapshot_entries(
        workflow,
        result.completed,
        task_id=task_run_id or result_id,
        task_duration_ms=duration_ms,
        source_filename=source_filename,
    )
    primary = snapshot_entries[0] if snapshot_entries else None
    output_content = str(primary.get("content", "")) if primary else ""
    output_format = str(primary.get("output_format", "")) if primary else ""
    raw_duration = primary.get("duration_ms") if primary else None
    processing_time_ms = (
        int(raw_duration) if isinstance(raw_duration, (int, float)) else duration_ms
    )
    node_summary = {
        "total": len(workflow.nodes),
        "completed": len(result.completed),
        "failed": len(result.failed),
    }
    summary = await repository.finalize_result(
        result_id,
        outcome_status="completed" if not result.failed else "failed",
        output_content=output_content or None,
        output_format=output_format or None,
        processing_time_ms=processing_time_ms,
        error=("; ".join(result.failed.values()) if result.failed else None),
        task_run_results=snapshot_entries,
        task_run_node_summary=node_summary,
        task_run_result_preview=(
            str(primary.get("result_preview", ""))[:RESULT_PREVIEW_MAX_CHARS] if primary else None
        ),
    )
    return {
        "result_id": result_id,
        "status": (summary or {}).get("result_status", "completed"),
        "run_status": (summary or {}).get("run_status"),
        "run_id": (summary or {}).get("run_id"),
    }


async def _finalize_evaluation_failure(
    *,
    repository: "EvaluationRepository",
    result_id: str,
    task_run_id: str | None,
    error: Exception,
    workflow: WorkflowDefinition,
    started_at: datetime,
) -> dict[str, object]:
    failed_at = _now()
    duration_ms = max(int((failed_at - started_at).total_seconds() * 1000), 0)
    error_message = str(error)
    node_summary = {
        "total": len(workflow.nodes),
        "completed": 0,
        "failed": max(len(workflow.nodes), 1),
    }
    summary = await repository.finalize_result(
        result_id,
        outcome_status="failed",
        output_content=None,
        output_format=None,
        processing_time_ms=duration_ms,
        error=error_message,
        task_run_results=[],
        task_run_node_summary=node_summary,
        task_run_result_preview=None,
    )
    return {
        "result_id": result_id,
        "status": "failed",
        "run_status": (summary or {}).get("run_status"),
        "run_id": (summary or {}).get("run_id"),
    }


def _execute_full_workflow_task_sync(
    *,
    task_run_id: str,
    workflow_def: dict[str, object],
    input_data: dict[str, object],
    context_data: dict[str, object] | None,
) -> dict[str, object]:
    context_data = context_data or {}
    workspace_id = _optional_str(context_data.get("workspace_id"))
    if workspace_id is None:
        raise ValueError("Queue workflow requires workspace scope")
    _validate_input_workspace(input_data, workspace_id)
    workflow = WorkflowDefinition.model_validate(workflow_def)
    input_bindings = {
        node_id: TaskInputFile.model_validate(binding)
        for node_id, binding in input_data.items()
        if isinstance(binding, dict)
    }
    if not input_bindings:
        raise ValueError("Celery task input_data does not contain input bindings")

    started_at = _now()
    with SessionLocal() as session:
        _validate_job_scope(session, context_data, workspace_id)
        _upsert_task_run(
            session,
            task_run_id=task_run_id,
            status="running",
            workflow_id=_optional_str(context_data.get("workflow_id")),
            workflow_name=_optional_str(context_data.get("workflow_name")),
            run_name=_optional_str(context_data.get("run_name")),
            source=_optional_str(context_data.get("source")) or "manual",
            evaluation_run_id=_optional_str(context_data.get("evaluation_run_id")),
            workspace_id=workspace_id,
            error=None,
            updated_at=started_at,
        )
        session.commit()

    store = ProviderStore(db_path=get_db_path(), fernet=get_fernet())
    scheduler = DAGScheduler(
        event_store=_WorkerEventStore(),
        node_registry=NodeRegistryService(),
        storage=get_storage(),
    )
    engine_client = EngineClient(settings=get_settings())
    try:
        result = execute_workflow_sync(
            workflow=workflow,
            task_id=task_run_id,
            input_bindings=input_bindings,
            workspace_id=workspace_id,
            dag_scheduler=scheduler,
            engine_client=engine_client,
            auth_resolver=AuthResolver(fernet=get_fernet()),
            provider_store=store,
        )
    except Exception as exc:
        failed_at = _now()
        with SessionLocal() as session:
            _upsert_task_run(
                session,
                task_run_id=task_run_id,
                status="failed",
                error=str(exc),
                completed_at=failed_at,
                updated_at=failed_at,
            )
            session.commit()
        raise
    finally:
        import asyncio

        asyncio.run(engine_client.close())

    completed_at = _now()
    duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
    source_filename = next(iter(input_bindings.values())).filename if input_bindings else None
    results = build_final_output_snapshot_entries(
        workflow,
        result.completed,
        task_id=task_run_id,
        task_duration_ms=duration_ms,
        source_filename=source_filename,
    )
    with SessionLocal() as session:
        for node_id, _output in result.completed.items():
            node = workflow.get_node(node_id)
            if node is None:
                continue
            _upsert_node_run(
                session,
                task_run_id=task_run_id,
                node_id=node_id,
                node_type=node.type,
                status="completed",
                duration_ms=duration_ms,
                completed_at=completed_at,
                updated_at=completed_at,
            )
        for node_id, error in result.failed.items():
            node = workflow.get_node(node_id)
            if node is None:
                continue
            _upsert_node_run(
                session,
                task_run_id=task_run_id,
                node_id=node_id,
                node_type=node.type,
                status="failed",
                duration_ms=duration_ms,
                error=error,
                completed_at=completed_at,
                updated_at=completed_at,
            )
        status = "failed" if result.failed else "completed"
        _upsert_task_run(
            session,
            task_run_id=task_run_id,
            status=status,
            duration_ms=duration_ms,
            completed_at=completed_at,
            node_summary={
                "total": len(workflow.nodes),
                "completed": len(result.completed),
                "failed": len(result.failed),
            },
            result_preview=(
                str(results[0].get("result_preview", ""))[:RESULT_PREVIEW_MAX_CHARS]
                if results
                else _build_result_preview(
                    next((output.model_dump() for output in result.completed.values()), {})
                )
            ),
            results=results,
            error="; ".join(result.failed.values()) if result.failed else None,
            updated_at=completed_at,
        )
        session.commit()
    return {"task_run_id": task_run_id, "status": status}


class _WorkerEventStore(EventStore):
    def append(self, event: ExecutionEvent) -> None:
        _ = event
        return None

    def compute_state(self, workflow_run_id: str) -> dict[str, NodeOutput]:
        _ = workflow_run_id
        return {}

    def get_max_sequence(self, workflow_run_id: str) -> int | None:
        _ = workflow_run_id
        return None


def _resolve_engine_node(workflow_def: dict[str, object]) -> dict[str, object]:
    nodes_value = workflow_def.get("nodes", [])
    nodes = nodes_value if isinstance(nodes_value, list) else []
    for node in nodes:
        if isinstance(node, dict) and str(node.get("type", "")).startswith("engine/"):
            return node
    raise ValueError("Workflow definition does not contain engine node")


def _parse_engine_type(node_type: str) -> str:
    if not node_type.startswith("engine/"):
        return "ocr"
    return node_type.split("/", 1)[1] or "ocr"


def _resolve_input_file_path(
    workflow_def: dict[str, object],
    input_data: dict[str, object],
    engine_node_id: str,
) -> str:
    connections_value = workflow_def.get("connections", [])
    connections = connections_value if isinstance(connections_value, list) else []

    predecessor_ids: list[str] = []
    for item in connections:
        if not isinstance(item, dict):
            continue
        if str(item.get("target", "")) != engine_node_id:
            continue
        source = item.get("source")
        if isinstance(source, str):
            predecessor_ids.append(source)

    for node_id in predecessor_ids:
        candidate = input_data.get(node_id)
        path = _extract_file_path(candidate)
        if path is not None:
            return path

    for candidate in input_data.values():
        path = _extract_file_path(candidate)
        if path is not None:
            return path

    raise ValueError("Celery task input_data does not contain file_path")


def _sanitize_engine_config(config: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in config.items()
        if key not in {"fallback_engine", "fallback_config"}
    }


def _resolve_fallback_settings(
    *,
    config: dict[str, object],
    primary_engine: str,
) -> tuple[str | None, dict[str, object]]:
    fallback_value = config.get("fallback_engine")
    if not isinstance(fallback_value, str) or not fallback_value.strip():
        return None, {}

    normalized = fallback_value.strip().lower()
    if normalized.startswith("engine/"):
        normalized = normalized.split("/", 1)[1]
    if not normalized or normalized == primary_engine:
        return None, {}

    raw_fallback_config = config.get("fallback_config")
    if isinstance(raw_fallback_config, dict):
        fallback_config = dict(raw_fallback_config)
    else:
        fallback_config = {}

    return normalized, fallback_config


def _try_fallback_engine_sync(
    *,
    task_run_id: str,
    node_id: str,
    node_type: str,
    input_file_path: str,
    primary_engine: str,
    fallback_engine: str | None,
    fallback_config: dict[str, object],
    primary_error: EngineError,
    workspace_id: str | None = None,
) -> tuple[dict[str, object] | None, EngineError | None]:
    if fallback_engine is None:
        return None, None

    if not _is_engine_healthy_sync(fallback_engine):
        logger.warning(
            "Skip queue fallback due to unhealthy engine: task_id=%s node_id=%s fallback_engine=%s",
            task_run_id,
            node_id,
            fallback_engine,
        )
        return None, None

    _append_node_fallback_event(
        task_run_id=task_run_id,
        node_id=node_id,
        node_type=node_type,
        primary_engine=primary_engine,
        fallback_engine=fallback_engine,
        primary_error=primary_error,
    )

    try:
        if workspace_id is not None:
            response = _call_engine_sync(
                engine_type=fallback_engine,
                input_file_path=input_file_path,
                config=fallback_config,
                workspace_id=workspace_id,
            )
        else:
            response = _call_engine_sync(
                engine_type=fallback_engine,
                input_file_path=input_file_path,
                config=fallback_config,
            )
        return response, None
    except Exception as exc:  # noqa: BLE001
        fallback_error = _normalize_engine_error(
            exc,
            engine_type=fallback_engine,
            node_id=node_id,
        )
        if isinstance(fallback_error.details, dict):
            fallback_error.details.setdefault("fallback_from", f"engine/{primary_engine}")
            fallback_error.details.setdefault("fallback_reason", primary_error.error_code.value)
        logger.warning(
            "Queue fallback failed: task_id=%s node_id=%s primary=%s fallback=%s error_type=%s",
            task_run_id,
            node_id,
            primary_engine,
            fallback_engine,
            type(fallback_error).__name__,
        )
        return None, fallback_error


def _is_engine_healthy_sync(
    engine_type: str,
) -> bool:
    try:
        engine_url = _resolve_engine_url(engine_type)
        with httpx.Client(timeout=FALLBACK_HEALTHCHECK_TIMEOUT_SECONDS) as client:
            response = client.get(f"{engine_url}/health")
            response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Queue fallback health check failed: engine=%s error_type=%s",
            engine_type,
            type(exc).__name__,
        )
        return False


def _extract_file_path(candidate: object) -> str | None:
    if not isinstance(candidate, dict):
        return None
    value = candidate.get("file_path")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _validate_input_workspace(input_data: dict[str, object], workspace_id: str | None) -> None:
    if workspace_id is None:
        return
    for candidate in input_data.values():
        if not isinstance(candidate, dict) or candidate.get("workspace_id") != workspace_id:
            raise ValueError("Queue input binding workspace does not match job workspace")


def _validate_job_scope(
    session: Session, context_data: dict[str, object], workspace_id: str | None
) -> None:
    if workspace_id is None:
        return
    for table_name, context_key in (
        ("workflows", "workflow_id"),
        ("evaluation_runs", "evaluation_run_id"),
    ):
        resource_id = _optional_str(context_data.get(context_key))
        columns = _table_columns(session, table_name)
        if resource_id is None or not {"id", "workspace_id"}.issubset(columns):
            continue
        scoped_id = session.execute(
            text(
                f"SELECT id FROM {table_name} "
                "WHERE id = :resource_id AND workspace_id = :workspace_id"
            ),
            {"resource_id": resource_id, "workspace_id": workspace_id},
        ).scalar_one_or_none()
        if scoped_id is None:
            raise ValueError(f"{context_key} is unavailable in the job workspace")


def _is_retryable_engine_error(error: EngineError) -> bool:
    return error.error_code in RETRYABLE_ENGINE_ERRORS


def _compute_queue_retry_delay_seconds(retries: int) -> int:
    seconds = QUEUE_TASK_DEFAULT_RETRY_DELAY_SECONDS * (2 ** max(retries, 0))
    return int(min(seconds, QUEUE_TASK_RETRY_BACKOFF_MAX_SECONDS))


def _retry_or_raise_engine_error(
    *,
    task_self: RetryCapableTask,
    error: EngineError,
    task_run_id: str,
    node_id: str,
    node_type: str,
) -> None:
    retries = int(getattr(getattr(task_self, "request", object()), "retries", 0))
    max_retries = int(getattr(task_self, "max_retries", QUEUE_TASK_MAX_RETRIES))
    if (not _is_retryable_engine_error(error)) or retries >= max_retries:
        raise error

    delay_seconds = _compute_queue_retry_delay_seconds(retries)
    _append_node_retry_event(
        task_run_id=task_run_id,
        node_id=node_id,
        node_type=node_type,
        retry_count=retries + 1,
        max_retries=max_retries,
        next_retry_delay_ms=delay_seconds * 1000,
        error=error,
    )
    raise task_self.retry(exc=error, countdown=delay_seconds)


def _append_node_retry_event(
    *,
    task_run_id: str,
    node_id: str,
    node_type: str,
    retry_count: int,
    max_retries: int,
    next_retry_delay_ms: int,
    error: EngineError,
) -> None:
    created_at = _now()
    with SessionLocal() as session:
        _upsert_task_run(
            session,
            task_run_id=task_run_id,
            status="running",
            error=None,
            updated_at=created_at,
        )
        _upsert_node_run(
            session,
            task_run_id=task_run_id,
            node_id=node_id,
            node_type=node_type,
            status="running",
            error=error.message,
            updated_at=created_at,
        )
        _append_task_event(
            session,
            task_run_id=task_run_id,
            event_type="node_retry",
            payload={
                "task_id": task_run_id,
                "node_id": node_id,
                "node_type": node_type,
                "timestamp": created_at.isoformat(),
                "retry_count": retry_count,
                "max_retries": max_retries,
                "next_retry_delay_ms": next_retry_delay_ms,
                "error_code": error.error_code.value,
                "message": error.message,
            },
            created_at=created_at,
        )
        session.commit()


def _append_node_fallback_event(
    *,
    task_run_id: str,
    node_id: str,
    node_type: str,
    primary_engine: str,
    fallback_engine: str,
    primary_error: EngineError,
) -> None:
    created_at = _now()
    reason = primary_error.error_code.value
    message = (
        f"{primary_engine.upper()} engine failed ({reason}), "
        f"falling back to {fallback_engine.upper()} engine"
    )
    with SessionLocal() as session:
        _upsert_task_run(
            session,
            task_run_id=task_run_id,
            status="running",
            error=None,
            updated_at=created_at,
        )
        _upsert_node_run(
            session,
            task_run_id=task_run_id,
            node_id=node_id,
            node_type=node_type,
            status="running",
            error=primary_error.message,
            updated_at=created_at,
        )
        _append_task_event(
            session,
            task_run_id=task_run_id,
            event_type="node_fallback",
            payload={
                "task_id": task_run_id,
                "node_id": node_id,
                "node_type": node_type,
                "timestamp": created_at.isoformat(),
                "original_engine": f"engine/{primary_engine}",
                "fallback_engine": f"engine/{fallback_engine}",
                "reason": reason,
                "message": message,
            },
            created_at=created_at,
        )
        session.commit()


def _normalize_engine_error(
    exc: Exception,
    *,
    engine_type: str,
    node_id: str,
) -> EngineError:
    if isinstance(exc, EngineError):
        return exc

    details: dict[str, object] = {"engine": engine_type, "node_id": node_id}
    if isinstance(exc, httpx.TimeoutException):
        return EngineError(
            error_code=ErrorCode.ENGINE_TIMEOUT,
            message=str(exc),
            engine_name=engine_type,
            details=details,
        )
    if isinstance(exc, httpx.RequestError):
        return EngineError(
            error_code=ErrorCode.ENGINE_UNREACHABLE,
            message=str(exc),
            engine_name=engine_type,
            details=details,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None:
            details["status_code"] = status_code
        if status_code == 429:
            error_code = ErrorCode.ENGINE_RATE_LIMITED
        elif status_code is not None and status_code >= 500:
            error_code = ErrorCode.ENGINE_INTERNAL_ERROR
        else:
            error_code = ErrorCode.ENGINE_INVALID_RESPONSE
        return EngineError(
            error_code=error_code,
            message=str(exc),
            engine_name=engine_type,
            details=details,
        )
    if isinstance(exc, ValueError):
        return EngineError(
            error_code=ErrorCode.ENGINE_INVALID_RESPONSE,
            message=str(exc),
            engine_name=engine_type,
            details=details,
        )
    return EngineError(
        error_code=ErrorCode.ENGINE_INTERNAL_ERROR,
        message=str(exc),
        engine_name=engine_type,
        details=details,
    )


def _call_engine_sync(
    *,
    engine_type: str,
    input_file_path: str,
    config: dict[str, object],
    workspace_id: str | None = None,
) -> dict[str, object]:
    # Provider-aware queue execution uses DurableWorkflowExecutionService. This
    # legacy single-engine fallback is intentionally limited to built-in engines.
    _ = workspace_id
    timeout_config = get_engine_timeout_config()
    raw_page_count = config.get("page_count")
    page_count = int(raw_page_count) if isinstance(raw_page_count, int) else 1
    timeout_seconds = timeout_config.resolve_timeout_seconds(engine_type, page_count=page_count)
    engine_url = _resolve_engine_url(engine_type)
    file_path = Path(input_file_path)
    file_size = file_path.stat().st_size
    if file_size > MAX_INPUT_FILE_SIZE_BYTES:
        raise ValueError(
            f"Input file too large ({file_size} bytes, limit {MAX_INPUT_FILE_SIZE_BYTES} bytes): "
            f"{input_file_path}"
        )
    if file_size > MAX_INPUT_FILE_SIZE_BYTES // 2:
        logger.warning(
            "Large input file may cause high memory usage size_bytes=%d",
            file_size,
        )
    payload = {
        "input_type": "base64",
        "base64_data": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        "config": config,
    }
    if engine_type == "markitdown":
        suffix = file_path.suffix.lower()
        payload["file_extension"] = suffix or ".txt"
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(f"{engine_url}/process", json=payload)
        response.raise_for_status()
        body = response.json()

    if not isinstance(body, dict):
        raise ValueError("Engine response must be JSON object")
    return body


def _resolve_engine_url(engine_type: str) -> str:
    settings = get_settings()
    mapping = {
        "ocr": settings.ocr_engine_url,
        "vlm": settings.vlm_engine_url,
        "text": settings.text_engine_url,
        "markitdown": settings.markitdown_engine_url,
    }
    url = mapping.get(engine_type)
    if not url:
        raise ValueError(f"Unsupported engine type for queue task: {engine_type}")
    return str(url).rstrip("/")


def _build_result_preview(response_body: dict[str, object]) -> str:
    output = response_body.get("output", response_body)
    preview_source = output if isinstance(output, (dict, list)) else response_body
    preview = json.dumps(preview_source, ensure_ascii=False)
    return preview[:RESULT_PREVIEW_MAX_CHARS]


def _upsert_task_run(
    session: Session,
    *,
    task_run_id: str,
    status: str,
    workflow_id: str | None = None,
    workflow_name: str | None = None,
    run_name: str | None = None,
    source: str | None = None,
    evaluation_run_id: str | None = None,
    workspace_id: str | None = None,
    duration_ms: int | None = None,
    completed_at: datetime | None = None,
    node_summary: dict[str, int] | None = None,
    result_preview: str | None = None,
    results: list[dict[str, object]] | None = None,
    error: str | None = None,
    updated_at: datetime | None = None,
) -> None:
    columns = _table_columns(session, "task_runs")
    if "id" not in columns:
        return

    insert_columns = ["id"]
    insert_values: dict[str, object] = {"task_id": task_run_id}
    if "source" in columns:
        insert_columns.append("source")
        insert_values["source"] = "worker"
    if "created_at" in columns:
        insert_columns.append("created_at")
        insert_values["created_at"] = datetime.utcnow()
    column_sql = ", ".join(insert_columns)
    value_sql = ", ".join(
        ":task_id" if column == "id" else f":{column}" for column in insert_columns
    )
    session.execute(
        text(
            f"INSERT INTO task_runs ({column_sql}) VALUES ({value_sql}) ON CONFLICT(id) DO NOTHING"
        ),
        insert_values,
    )

    updates: dict[str, object] = {}
    if "status" in columns:
        updates["status"] = status
    if "workflow_id" in columns:
        updates["workflow_id"] = workflow_id
    if "workflow_name" in columns:
        updates["workflow_name"] = workflow_name
    if "run_name" in columns:
        updates["run_name"] = run_name
    if "source" in columns:
        updates["source"] = source
    if "evaluation_run_id" in columns:
        updates["evaluation_run_id"] = evaluation_run_id
    if "workspace_id" in columns and workspace_id is not None:
        updates["workspace_id"] = workspace_id
    if "duration_ms" in columns and duration_ms is not None:
        updates["duration_ms"] = duration_ms
    if "completed_at" in columns and completed_at is not None:
        updates["completed_at"] = completed_at
    if "node_summary_json" in columns and node_summary is not None:
        updates["node_summary_json"] = json.dumps(node_summary, ensure_ascii=False)
    if "result_preview" in columns and result_preview is not None:
        updates["result_preview"] = result_preview[:RESULT_PREVIEW_MAX_CHARS]
    if "results_json" in columns and results is not None:
        updates["results_json"] = json.dumps(results, ensure_ascii=False)
    if "error" in columns:
        updates["error"] = error
    if "updated_at" in columns and updated_at is not None:
        updates["updated_at"] = updated_at

    if not updates:
        return

    set_clause = ", ".join(f"{column} = :{column}" for column in updates)
    session.execute(
        text(
            f"UPDATE task_runs SET {set_clause} WHERE id = :task_id "
            "AND (status IS NULL OR status != 'cancelled')"
        ),
        {"task_id": task_run_id, **updates},
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if text_value else None


def _upsert_node_run(
    session: Session,
    *,
    task_run_id: str,
    node_id: str,
    node_type: str,
    status: str,
    duration_ms: int | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    columns = _table_columns(session, "node_runs")
    if not columns:
        return

    id_column = "node_run_id" if "node_run_id" in columns else ("id" if "id" in columns else None)
    record_id = f"{task_run_id}:{node_id}"

    if id_column is not None:
        insert_values: dict[str, object] = {id_column: record_id}
        if "task_run_id" in columns:
            insert_values["task_run_id"] = task_run_id
        if "node_id" in columns:
            insert_values["node_id"] = node_id
        if "node_type" in columns:
            insert_values["node_type"] = node_type

        insert_columns = ", ".join(insert_values.keys())
        insert_params = ", ".join(f":{column}" for column in insert_values.keys())
        session.execute(
            text(
                "INSERT INTO node_runs "
                f"({insert_columns}) VALUES ({insert_params}) "
                f"ON CONFLICT({id_column}) DO NOTHING"
            ),
            insert_values,
        )

        updates: dict[str, object] = {}
        if "task_run_id" in columns:
            updates["task_run_id"] = task_run_id
        if "node_id" in columns:
            updates["node_id"] = node_id
        if "node_type" in columns:
            updates["node_type"] = node_type
        if "status" in columns:
            updates["status"] = status
        if "attempt" in columns:
            updates["attempt"] = 1
        if "duration_ms" in columns and duration_ms is not None:
            updates["duration_ms"] = duration_ms
        if "error" in columns:
            updates["error"] = error
        if "started_at" in columns and started_at is not None:
            updates["started_at"] = started_at
        if "completed_at" in columns and completed_at is not None:
            updates["completed_at"] = completed_at
        if "updated_at" in columns and updated_at is not None:
            updates["updated_at"] = updated_at

        if updates:
            set_clause = ", ".join(f"{column} = :{column}" for column in updates)
            session.execute(
                text(f"UPDATE node_runs SET {set_clause} WHERE {id_column} = :node_run_record_id"),
                {"node_run_record_id": record_id, **updates},
            )
        return

    insert_values = {
        key: value
        for key, value in {
            "task_run_id": task_run_id,
            "node_id": node_id,
            "node_type": node_type,
            "status": status,
            "attempt": 1,
            "duration_ms": duration_ms,
            "error": error,
            "started_at": started_at,
            "completed_at": completed_at,
            "updated_at": updated_at,
        }.items()
        if key in columns and value is not None
    }
    if not insert_values:
        return

    column_sql = ", ".join(insert_values.keys())
    values_sql = ", ".join(f":{column}" for column in insert_values.keys())
    session.execute(
        text(f"INSERT INTO node_runs ({column_sql}) VALUES ({values_sql})"),
        insert_values,
    )


def _append_task_event(
    session: Session,
    *,
    task_run_id: str,
    event_type: str,
    payload: dict[str, object],
    created_at: datetime,
) -> None:
    columns = _table_columns(session, "task_event_logs")
    if not columns:
        return

    payload_column = "payload" if "payload" in columns else "payload_json"
    values = {
        key: value
        for key, value in {
            "task_run_id": task_run_id,
            "event_type": event_type,
            payload_column: json.dumps(payload, ensure_ascii=False) if payload_column else None,
            "created_at": created_at,
        }.items()
        if key in columns and value is not None
    }

    if not values:
        return

    column_sql = ", ".join(values.keys())
    values_sql = ", ".join(f":{column}" for column in values.keys())
    session.execute(
        text(f"INSERT INTO task_event_logs ({column_sql}) VALUES ({values_sql})"),
        values,
    )


_column_cache: dict[tuple[str, str], set[str]] = {}


def _table_columns(session: Session, table_name: str) -> set[str]:
    bind = session.get_bind()
    engine = bind.engine if isinstance(bind, sa.Connection) else bind
    cache_key = (str(engine.url), table_name)
    if cache_key in _column_cache:
        return _column_cache[cache_key]
    inspector = sa.inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    columns = {str(column["name"]) for column in inspector.get_columns(table_name)}
    _column_cache[cache_key] = columns
    return columns


def _now() -> datetime:
    return datetime.now(timezone.utc)
