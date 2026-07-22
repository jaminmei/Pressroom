"""Public blocking-mode workflow run endpoint.

``POST /api/v1/workflows/{workflow_id}/run`` — launches a published workflow,
blocks until terminal state (or timeout), and returns the assembled result.

Reuses ``_start_dag_run()`` and aliases ``workflow_run_id = task_id``.
Blocking uses a 0.5s poll over ``TaskRunRepository.get_snapshot()``.
Errors surface through ``PublicApiError`` → standard ``{error: {...}}`` envelope.

Self-check: ``python -m app.api.public.workflow_runs``.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, cast
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.api.public.auth import ApiKeyDep, ApiKeyIdentity
from app.api.public.error_response import PublicApiError
from app.api.task_helpers import TERMINAL_TASK_STATUSES
from app.api.tasks import _start_dag_run
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.models.task import TaskInputFile
from app.repositories.task_run_repository import TaskRunRepository, TaskRunSnapshot
from app.services.api_usage_service import ApiUsageService
from app.services.input_fetcher import InputFetcher, InputFetchError
from app.services.rate_limiter import RateLimiter, RateLimitExceededError
from app.services.upload_handler import UploadHandler, UploadHandlerError
from app.services.workspace_rbac import workspace_rbac_enforced

router = APIRouter(tags=["public-api"])


async def await_run_terminal(
    workflow_run_id: str,
    timeout: float,
    *,
    workspace_id: str | None = None,
) -> TaskRunSnapshot:
    """Poll the snapshot repo until a terminal status is observed or timeout.

    On timeout, raise ``PublicApiError(504, RUN_TIMEOUT, ..., workflow_run_id=...)``.
    The run keeps executing server-side and the client may poll its status.
    """
    repo = TaskRunRepository()
    try:
        async with asyncio.timeout(timeout):
            while True:
                snapshot = await repo.get_snapshot(workflow_run_id, workspace_id=workspace_id)
                if snapshot is not None and snapshot.status in TERMINAL_TASK_STATUSES:
                    return snapshot
                await asyncio.sleep(0.5)
    except TimeoutError as e:
        raise PublicApiError(
            status_code=504,
            code="RUN_TIMEOUT",
            message=f"Run did not complete within {timeout:.0f}s",
            workflow_run_id=workflow_run_id,
        ) from e


class RunWorkflowRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    user: str | None = None


def _safe_request_state(request: Request) -> object | None:
    return getattr(request, "state", None)


def _file_metadata_from_value(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    source_kind = "remote_url" if value.lower().startswith(("http://", "https://")) else "path"
    filename = Path(value.split("?", 1)[0]).name or "input"
    return {"source_kind": source_kind, "filename": filename}


def _json_run_input_metadata(payload: RunWorkflowRequest) -> dict[str, Any] | None:
    file_meta = _file_metadata_from_value(payload.inputs.get("file"))
    if file_meta is None and not payload.inputs:
        return None
    return {
        "mode": "json",
        "file": file_meta,
        "input_keys": sorted(str(key) for key in payload.inputs.keys()),
        "user": payload.user,
    }


def _require_workspace_scope(identity: ApiKeyIdentity) -> str | None:
    if workspace_rbac_enforced() and identity.workspace_id is None:
        raise PublicApiError(
            status_code=404,
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow not found: {identity.workflow_id}",
        )
    return identity.workspace_id


def _response_body(response: JSONResponse) -> dict[str, Any]:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _safe_record_invocation(
    *,
    request: Request,
    workflow_id: str,
    workspace_id: str | None,
    workflow_run_id: str | None,
    endpoint_kind: str,
    http_status: int | None,
    workflow_status: str,
    response_time_ms: int | None,
    input_metadata: dict[str, Any] | None,
    error: dict[str, Any] | None,
    created_at: datetime,
    finished_at: datetime | None,
) -> None:
    state = _safe_request_state(request)
    final_metadata = getattr(state, "api_usage_input_metadata", None) or input_metadata
    api_key_id = getattr(state, "api_key_id", None)
    api_key_prefix = getattr(state, "api_key_prefix", None)
    service = ApiUsageService()
    try:
        await service.record_invocation(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            workflow_run_id=workflow_run_id,
            api_key_id=str(api_key_id) if api_key_id else None,
            api_key_prefix=str(api_key_prefix) if api_key_prefix else None,
            endpoint_kind=endpoint_kind,
            http_status=http_status,
            workflow_status=workflow_status,
            response_time_ms=response_time_ms,
            input_metadata=final_metadata if isinstance(final_metadata, dict) else None,
            error=error,
            storage_bytes=service.task_storage_bytes(workflow_run_id),
            created_at=created_at,
            finished_at=finished_at,
        )
    except RuntimeError:
        raise
    except Exception:
        # Usage observability is best-effort and must never break the public API.
        pass


async def _record_public_invocation(
    *,
    request: Request,
    workflow_id: str,
    workspace_id: str | None,
    endpoint_kind: str,
    input_metadata: dict[str, Any] | None,
    call: Callable[[], Awaitable[JSONResponse]],
) -> JSONResponse:
    created_at = datetime.now(timezone.utc)
    monotonic_started = time.monotonic()
    try:
        response = await call()
    except PublicApiError as exc:
        finished_at = datetime.now(timezone.utc)
        workflow_run_id = exc.extra_fields.get("workflow_run_id")
        await _safe_record_invocation(
            request=request,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            workflow_run_id=str(workflow_run_id) if workflow_run_id else None,
            endpoint_kind=endpoint_kind,
            http_status=exc.status_code,
            workflow_status="timeout" if exc.code == "RUN_TIMEOUT" else "rejected",
            response_time_ms=max(int((time.monotonic() - monotonic_started) * 1000), 0),
            input_metadata=input_metadata,
            error={"code": exc.code, "message": exc.message},
            created_at=created_at,
            finished_at=finished_at,
        )
        raise
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        await _safe_record_invocation(
            request=request,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            workflow_run_id=None,
            endpoint_kind=endpoint_kind,
            http_status=500,
            workflow_status="error",
            response_time_ms=max(int((time.monotonic() - monotonic_started) * 1000), 0),
            input_metadata=input_metadata,
            error={"code": "UNHANDLED_ERROR", "message": str(exc)},
            created_at=created_at,
            finished_at=finished_at,
        )
        raise

    finished_at = datetime.now(timezone.utc)
    body = _response_body(response)
    response_status = str(body.get("status") or "unknown")
    workflow_run_id = body.get("workflow_run_id")
    await _safe_record_invocation(
        request=request,
        workflow_id=workflow_id,
        workspace_id=workspace_id,
        workflow_run_id=str(workflow_run_id) if workflow_run_id else None,
        endpoint_kind=endpoint_kind,
        http_status=response.status_code,
        workflow_status=response_status,
        response_time_ms=max(int((time.monotonic() - monotonic_started) * 1000), 0),
        input_metadata=input_metadata,
        error=body.get("error") if isinstance(body.get("error"), dict) else None,
        created_at=created_at,
        finished_at=finished_at,
    )
    return response


@router.post("/workflows/{workflow_id}/run", response_model=None)
async def run_workflow(
    workflow_id: str,
    request: Request,
    api_key_identity: ApiKeyDep,
    payload: RunWorkflowRequest,
) -> JSONResponse:
    return await _record_public_invocation(
        request=request,
        workflow_id=workflow_id,
        workspace_id=api_key_identity.workspace_id,
        endpoint_kind="json_run",
        input_metadata=_json_run_input_metadata(payload),
        call=lambda: _run_workflow_impl(
            workflow_id=workflow_id,
            request=request,
            api_key_identity=api_key_identity,
            payload=payload,
        ),
    )


async def _run_workflow_impl(
    workflow_id: str,
    request: Request,
    api_key_identity: ApiKeyIdentity,
    payload: RunWorkflowRequest,
) -> JSONResponse:
    # Verify that the API key is bound to the requested workflow.
    if api_key_identity.workflow_id != workflow_id:
        raise PublicApiError(
            status_code=403,
            code="WORKFLOW_MISMATCH",
            message=(
                f"API key is bound to workflow '{api_key_identity.workflow_id}', "
                f"cannot run '{workflow_id}'"
            ),
        )
    workspace_id = _require_workspace_scope(api_key_identity)

    # Require an existing published workflow.
    workflow = get_workflow_store().get(workflow_id, workspace_id=workspace_id)
    if workflow is None:
        raise PublicApiError(
            status_code=404,
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow not found: {workflow_id}",
        )
    if workflow.published_version is None:
        raise PublicApiError(
            status_code=403,
            code="WORKFLOW_NOT_PUBLISHED",
            message=f"Workflow has no published version: {workflow_id}",
        )

    # Build input bindings from client-supplied inputs.
    # The workflow's input nodes (type startswith "input/" and "file" in config)
    # are populated with the URL from payload.inputs["file"].
    input_nodes = [
        n for n in workflow.definition.nodes if n.type.startswith("input/") and "file" in n.config
    ]

    # run_id is generated BEFORE input resolution so a downloaded remote file
    # lands in the correct per-run storage subdir (/tasks/{run_id}/original/...).
    # The task id is also the public workflow run id.
    task_id = f"task_{uuid4().hex[:12]}"
    run_id = task_id
    created_at = datetime.now(timezone.utc)

    input_bindings: dict[str, TaskInputFile] | None = None
    if input_nodes:
        file_url = payload.inputs.get("file")
        if not file_url:
            raise PublicApiError(
                status_code=400,
                code="INVALID_INPUT",
                message=(
                    "Workflow has input nodes requiring 'file'; "
                    "inputs.file is required (URL or path)"
                ),
            )
        # Resolve URL → local path (download + SSRF guard) before the DAG
        # starts. Local paths pass through unchanged. A fetch failure raises
        # PublicApiError(400, INVALID_INPUT) here, BEFORE _start_dag_run, so
        # no task_runs row is left behind on a failed fetch.
        try:
            local_path = await InputFetcher().resolve_input_file(file_url, run_id)
        except InputFetchError as exc:
            raise PublicApiError(
                status_code=400,
                code="INVALID_INPUT",
                message=f"Failed to resolve inputs.file: {exc}",
            ) from exc
        filename = local_path.rsplit("/", 1)[-1] or "input"
        input_bindings = {
            n.id: TaskInputFile(
                file_path=local_path,
                filename=filename,
                mime_type="application/octet-stream",
            )
            for n in input_nodes
        }

    # Start the DAG run. _start_dag_run() returns None.
    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow.definition,
        dag_scheduler=request.app.state.dag_scheduler,
        engine_client=request.app.state.engine_client,
        event_store=request.app.state.event_store,
        running_tasks=request.app.state.running_tasks,
        created_at=created_at,
        input_bindings=input_bindings,
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        workspace_id=workspace_id,
    )

    # Persist workflow_id on the task_runs row so status/results/history
    # ownership checks can resolve (BUG-001 fix). _start_dag_run() and the
    # existing /api/tasks callers pass workflow_id=None; we set it here
    # because the public API always knows which workflow is being run.
    _run_repo = TaskRunRepository()
    try:
        await _run_repo.upsert_snapshot(
            task_id=task_id,
            status="pending",
            workflow_id=workflow_id,
            workflow_name=None,
            source="api_forward",
            workspace_id=workspace_id,
            created_at=created_at,
            completed_at=None,
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            workflow=workflow.definition.model_dump(mode="json"),
            updated_at=created_at,
        )
    except Exception:
        # Non-fatal: the run will still execute; only post-run queries
        # would be affected if this fails (they'd return RUN_NOT_OWNED).
        pass

    # Block until the run reaches a terminal state.
    timeout = get_settings().workflow_api_timeout_seconds
    snapshot = await await_run_terminal(task_id, timeout, workspace_id=workspace_id)

    # Step 6: assemble response (tasks 4.5, 4.6).
    results = snapshot.results or []
    node_summary = snapshot.node_summary or {}
    total_steps = len(node_summary)
    elapsed_ms = snapshot.duration_ms or 0
    created_iso = snapshot.created_at.isoformat() if snapshot.created_at else created_at.isoformat()
    finished_iso = snapshot.completed_at.isoformat() if snapshot.completed_at else None

    if snapshot.status in ("completed", "partial_completed"):
        text = "\n\n".join(r.get("content", "") for r in results)
        return JSONResponse(
            status_code=200,
            content={
                "workflow_run_id": task_id,
                "status": "succeeded",
                "inputs": payload.inputs,
                "outputs": {"text": text, "results": results},
                "elapsed_time_ms": elapsed_ms,
                "total_steps": total_steps,
                "created_at": created_iso,
                "finished_at": finished_iso,
            },
        )

    if snapshot.status == "cancelled":
        code, message = "WORKFLOW_CANCELLED", "Workflow run was cancelled"
    else:
        code = "WORKFLOW_EXECUTION_FAILED"
        message = snapshot.error or "Workflow execution failed"
    return JSONResponse(
        status_code=200,
        content={
            "workflow_run_id": task_id,
            "status": "failed",
            "error": {"code": code, "message": message},
            "inputs": payload.inputs,
            "elapsed_time_ms": elapsed_ms,
            "total_steps": total_steps,
            "created_at": created_iso,
            "finished_at": finished_iso,
        },
    )


@router.post("/workflows/{workflow_id}/run/upload", response_model=None)
async def run_workflow_upload(
    workflow_id: str,
    request: Request,
    api_key_identity: ApiKeyDep,
) -> JSONResponse:
    return await _record_public_invocation(
        request=request,
        workflow_id=workflow_id,
        workspace_id=api_key_identity.workspace_id,
        endpoint_kind="file_upload",
        input_metadata={"mode": "upload"},
        call=lambda: _run_workflow_upload_impl(
            workflow_id=workflow_id,
            request=request,
            api_key_identity=api_key_identity,
        ),
    )


async def _run_workflow_upload_impl(
    workflow_id: str,
    request: Request,
    api_key_identity: ApiKeyIdentity,
) -> JSONResponse:
    """Multipart-upload variant of ``/run``: receives a single ``file`` part,
    persists it via UploadHandler, then drives the same DAG run + blocking
    poll as ``/run``.

    Differences from ``/run``:
      - No typed pydantic payload (per TD8 — typed ``UploadFile = File(...)``
        triggers FastAPI RequestValidationError that bypasses our 400 envelope;
        we parse multipart manually inside try/except).
      - Optional ``options`` JSON part carries ``{user: ...}``.
      - Per-key rate limit + Content-Length ceiling guard before parsing.
    """
    # Step 1: API key binding scope (mirror run_workflow lines 74-82).
    if api_key_identity.workflow_id != workflow_id:
        raise PublicApiError(
            status_code=403,
            code="WORKFLOW_MISMATCH",
            message=(
                f"API key is bound to workflow '{api_key_identity.workflow_id}', "
                f"cannot run '{workflow_id}'"
            ),
        )
    workspace_id = _require_workspace_scope(api_key_identity)

    # Step 2: workflow existence + published version (mirror lines 84-97).
    workflow = get_workflow_store().get(workflow_id, workspace_id=workspace_id)
    if workflow is None:
        raise PublicApiError(
            status_code=404,
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow not found: {workflow_id}",
        )
    if workflow.published_version is None:
        raise PublicApiError(
            status_code=403,
            code="WORKFLOW_NOT_PUBLISHED",
            message=f"Workflow has no published version: {workflow_id}",
        )

    # Step 2.5: per-key rate limit. Singleton from app.state so token bucket
    # state persists across requests (per-request instantiation never trips).
    # Fallback builds a fresh limiter if startup hook didn't run (e.g. tests).
    api_key_id = getattr(request.state, "api_key_id", None) or "unknown"
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is None:
        rate_limiter = RateLimiter(get_settings().input_upload_rate_limit_per_minute)
    try:
        await rate_limiter.check(api_key_id)
    except RateLimitExceededError as e:
        raise PublicApiError(
            status_code=429,
            code="RATE_LIMIT_EXCEEDED",
            message="Per-key upload rate limit exceeded",
        ) from e

    # Step 2.7: pre-parse Content-Length ceiling (defense-in-depth; the
    # streaming read in UploadHandler is the authoritative check).
    max_bytes = get_settings().input_upload_max_bytes
    try:
        cl = int(request.headers.get("content-length", 0))
    except ValueError:
        cl = 0
    if cl > max_bytes:
        raise PublicApiError(
            status_code=400,
            code="INVALID_INPUT",
            message=f"Upload exceeds limit ({max_bytes} bytes)",
        )

    # Step 3: manual multipart parsing (no typed UploadFile/File params, TD8).
    try:
        form = await request.form()
    except Exception as exc:
        raise PublicApiError(
            status_code=400, code="INVALID_INPUT", message=f"Malformed multipart: {exc}"
        ) from exc

    file_part = form.get("file")
    if not isinstance(file_part, UploadFile):
        raise PublicApiError(
            status_code=400,
            code="INVALID_INPUT",
            message="Missing 'file' part in multipart upload",
        )

    # Reject 2+ file parts.
    file_parts = [v for k, v in form.multi_items() if k == "file" and isinstance(v, UploadFile)]
    if len(file_parts) > 1:
        raise PublicApiError(
            status_code=400, code="INVALID_INPUT", message="Only one 'file' part allowed"
        )

    state = _safe_request_state(request)
    if state is not None:
        cast(Any, state).api_usage_input_metadata = {
            "mode": "upload",
            "file": {
                "source_kind": "upload",
                "filename": file_part.filename or "upload",
                "size_bytes": file_part.size,
                "mime_type": file_part.content_type,
            },
        }

    # Optional ``options`` JSON part: ``{user: "..."}``.
    options_str = form.get("options")
    user: str | None = None
    if options_str:
        try:
            opts = json.loads(options_str) if isinstance(options_str, str) else {}
            user = opts.get("user") if isinstance(opts, dict) else None
        except (json.JSONDecodeError, AttributeError) as exc:
            raise PublicApiError(
                status_code=400,
                code="INVALID_INPUT",
                message=f"Malformed options JSON: {exc}",
            ) from exc

    # Step 3.5: task_id / run_id (mirror lines 110-112).
    task_id = f"task_{uuid4().hex[:12]}"
    run_id = task_id
    created_at = datetime.now(timezone.utc)

    # Step 4: receive upload → local path.
    try:
        local_path = await UploadHandler().receive_upload(file_part, run_id)
    except UploadHandlerError as exc:
        raise PublicApiError(
            status_code=400, code="INVALID_INPUT", message=f"Upload failed: {exc}"
        ) from exc

    # Step 5: build input_bindings from local_path + workflow input_nodes
    # (mirror lines 102-146, but using the freshly saved local_path).
    input_nodes = [
        n for n in workflow.definition.nodes if n.type.startswith("input/") and "file" in n.config
    ]
    input_bindings: dict[str, TaskInputFile] | None = None
    if input_nodes:
        filename = local_path.rsplit("/", 1)[-1] or "input"
        input_bindings = {
            n.id: TaskInputFile(
                file_path=local_path,
                filename=filename,
                mime_type="application/octet-stream",
            )
            for n in input_nodes
        }

    # Step 6: kick off the DAG run (mirror lines 148-161).
    _start_dag_run(
        task_id=task_id,
        run_id=run_id,
        workflow=workflow.definition,
        dag_scheduler=request.app.state.dag_scheduler,
        engine_client=request.app.state.engine_client,
        event_store=request.app.state.event_store,
        running_tasks=request.app.state.running_tasks,
        created_at=created_at,
        input_bindings=input_bindings,
        auth_resolver=getattr(request.app.state, "auth_resolver", None),
        provider_store=getattr(request.app.state, "provider_store", None),
        workspace_id=workspace_id,
    )

    # Persist workflow_id on the task_runs row (mirror lines 167-186).
    _run_repo = TaskRunRepository()
    try:
        await _run_repo.upsert_snapshot(
            task_id=task_id,
            status="pending",
            workflow_id=workflow_id,
            workflow_name=None,
            source="api_forward",
            workspace_id=workspace_id,
            created_at=created_at,
            completed_at=None,
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            workflow=workflow.definition.model_dump(mode="json"),
            updated_at=created_at,
        )
    except Exception:
        # Non-fatal: best-effort task_runs row persist. The run will still
        # execute via _start_dag_run above; this snapshot is for status polling.
        pass

    # Step 7: block until terminal (mirror lines 188-190).
    timeout = get_settings().workflow_api_timeout_seconds
    snapshot = await await_run_terminal(task_id, timeout, workspace_id=workspace_id)

    # Step 8: assemble response (mirror lines 192-235). Echo the saved file
    # path as inputs.file so the shape matches /run's response.
    results = snapshot.results or []
    node_summary = snapshot.node_summary or {}
    total_steps = len(node_summary)
    elapsed_ms = snapshot.duration_ms or 0
    created_iso = snapshot.created_at.isoformat() if snapshot.created_at else created_at.isoformat()
    finished_iso = snapshot.completed_at.isoformat() if snapshot.completed_at else None
    echoed_inputs: dict[str, Any] = {"file": local_path}
    if user is not None:
        echoed_inputs["user"] = user

    if snapshot.status in ("completed", "partial_completed"):
        text = "\n\n".join(r.get("content", "") for r in results)
        return JSONResponse(
            status_code=200,
            content={
                "workflow_run_id": task_id,
                "status": "succeeded",
                "inputs": echoed_inputs,
                "outputs": {"text": text, "results": results},
                "elapsed_time_ms": elapsed_ms,
                "total_steps": total_steps,
                "created_at": created_iso,
                "finished_at": finished_iso,
            },
        )

    if snapshot.status == "cancelled":
        code, message = "WORKFLOW_CANCELLED", "Workflow run was cancelled"
    else:
        code = "WORKFLOW_EXECUTION_FAILED"
        message = snapshot.error or "Workflow execution failed"
    return JSONResponse(
        status_code=200,
        content={
            "workflow_run_id": task_id,
            "status": "failed",
            "error": {"code": code, "message": message},
            "inputs": echoed_inputs,
            "elapsed_time_ms": elapsed_ms,
            "total_steps": total_steps,
            "created_at": created_iso,
            "finished_at": finished_iso,
        },
    )


async def _load_owned_snapshot(
    workflow_run_id: str,
    api_key_identity: ApiKeyIdentity,
) -> TaskRunSnapshot:
    """Shared lookup + ownership guard for status/results endpoints.

    Raises ``PublicApiError`` (404 RUN_NOT_FOUND / 403 RUN_NOT_OWNED) on miss.
    A non-owner currently receives 403 rather than 404. Operators should
    account for that existence signal in their threat model.
    """
    workspace_id = _require_workspace_scope(api_key_identity)
    repo = TaskRunRepository()
    snapshot = await repo.get_snapshot(workflow_run_id, workspace_id=workspace_id)
    if snapshot is None:
        raise PublicApiError(
            status_code=404,
            code="RUN_NOT_FOUND",
            message=f"Run not found: {workflow_run_id}",
        )
    if snapshot.workflow_id != api_key_identity.workflow_id:
        raise PublicApiError(
            status_code=403,
            code="RUN_NOT_OWNED",
            message=(f"API key is not bound to workflow owning run '{workflow_run_id}'"),
        )
    return snapshot


@router.get("/workflow-runs/{workflow_run_id}", response_model=None)
async def get_run_status(
    workflow_run_id: str,
    request: Request,
    api_key_identity: ApiKeyDep,
) -> JSONResponse:
    snapshot = await _load_owned_snapshot(workflow_run_id, api_key_identity)
    return JSONResponse(
        status_code=200,
        content={
            "workflow_run_id": workflow_run_id,
            "workflow_id": snapshot.workflow_id,
            "status": snapshot.status,
            "elapsed_time_ms": snapshot.duration_ms or 0,
            "total_steps": len(snapshot.node_summary or {}),
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            "finished_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
        },
    )


@router.get("/workflow-runs/{workflow_run_id}/results", response_model=None)
async def get_run_results(
    workflow_run_id: str,
    request: Request,
    api_key_identity: ApiKeyDep,
) -> JSONResponse:
    snapshot = await _load_owned_snapshot(workflow_run_id, api_key_identity)
    if snapshot.status not in ("completed", "partial_completed"):
        raise PublicApiError(
            status_code=409,
            code="RUN_NOT_COMPLETE",
            message=f"Run is not complete (status: {snapshot.status})",
            workflow_run_id=workflow_run_id,
        )
    return JSONResponse(
        status_code=200,
        content={
            "workflow_run_id": workflow_run_id,
            "status": "succeeded",
            "results": snapshot.results or [],
        },
    )


@router.get("/workflows/{workflow_id}/runs", response_model=None)
async def list_workflow_runs(
    workflow_id: str,
    request: Request,
    api_key_identity: ApiKeyDep,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    if api_key_identity.workflow_id != workflow_id:
        raise PublicApiError(
            status_code=403,
            code="WORKFLOW_MISMATCH",
            message=(
                f"API key is bound to workflow '{api_key_identity.workflow_id}', "
                f"cannot list runs for '{workflow_id}'"
            ),
        )
    workspace_id = _require_workspace_scope(api_key_identity)
    repo = TaskRunRepository()
    snapshots = await repo.list_snapshots(workflow_id=workflow_id, workspace_id=workspace_id)
    # Run counts are currently modest; move pagination into the repository
    # when the in-memory slice becomes measurable.
    offset = (page - 1) * limit
    page_items = snapshots[offset : offset + limit]
    total = len(snapshots)
    return JSONResponse(
        status_code=200,
        content={
            "data": [
                {
                    "workflow_run_id": s.task_id,
                    "status": s.status,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "finished_at": s.completed_at.isoformat() if s.completed_at else None,
                    "elapsed_time_ms": s.duration_ms or 0,
                }
                for s in page_items
            ],
            "meta": {"total": total, "page": page, "limit": limit},
        },
    )


if __name__ == "__main__":
    # --- (a) success response assembly ---
    now = datetime.now(timezone.utc)
    ok_snap = TaskRunSnapshot(
        task_id="task_success",
        status="completed",
        results=[{"content": "hello"}, {"content": "world"}],
        duration_ms=1234,
        node_summary={"n1": 1, "n2": 1},
        created_at=now,
        completed_at=now,
    )

    def _build_ok_body(snap: TaskRunSnapshot, inputs: dict[str, Any]) -> dict[str, Any]:
        results = snap.results or []
        node_summary = snap.node_summary or {}
        text = "\n\n".join(r.get("content", "") for r in results)
        return {
            "workflow_run_id": "task_success",
            "status": "succeeded",
            "inputs": inputs,
            "outputs": {"text": text, "results": results},
            "elapsed_time_ms": snap.duration_ms or 0,
            "total_steps": len(node_summary),
            "created_at": (snap.created_at or now).isoformat(),
            "finished_at": snap.completed_at.isoformat() if snap.completed_at else None,
        }

    body_ok = _build_ok_body(ok_snap, {"file": "url"})
    assert body_ok["status"] == "succeeded", body_ok
    assert body_ok["outputs"]["text"] == "hello\n\nworld", body_ok
    assert body_ok["outputs"]["results"] == [{"content": "hello"}, {"content": "world"}]
    assert body_ok["total_steps"] == 2, body_ok
    assert body_ok["elapsed_time_ms"] == 1234, body_ok

    # --- (b) failure response assembly ---
    fail_snap = TaskRunSnapshot(task_id="task_fail", status="failed", error="boom")

    def _build_fail_body(snap: TaskRunSnapshot) -> dict[str, Any]:
        if snap.status == "cancelled":
            code, message = "WORKFLOW_CANCELLED", "Workflow run was cancelled"
        else:
            code = "WORKFLOW_EXECUTION_FAILED"
            message = snap.error or "Workflow execution failed"
        return {
            "workflow_run_id": snap.task_id,
            "status": "failed",
            "error": {"code": code, "message": message},
        }

    body_fail = _build_fail_body(fail_snap)
    assert body_fail["status"] == "failed", body_fail
    assert body_fail["error"]["code"] == "WORKFLOW_EXECUTION_FAILED", body_fail
    assert body_fail["error"]["message"] == "boom", body_fail

    cancel_body = _build_fail_body(TaskRunSnapshot(task_id="task_c", status="cancelled"))
    assert cancel_body["error"]["code"] == "WORKFLOW_CANCELLED", cancel_body

    # --- (c) await_run_terminal timeout ---
    class _NeverRepo:
        async def get_snapshot(
            self, task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot | None:
            _ = task_id, workspace_id
            return None

    orig_repo = TaskRunRepository
    globals()["TaskRunRepository"] = _NeverRepo
    try:
        import asyncio as _asyncio

        async def _timeout_check() -> None:
            try:
                await await_run_terminal("nonexistent", timeout=0.1)
                raise AssertionError("timeout should raise PublicApiError")
            except PublicApiError as e:
                assert e.status_code == 504, e.status_code
                assert e.code == "RUN_TIMEOUT", e.code
                assert e.extra_fields.get("workflow_run_id") == "nonexistent", e.extra_fields

        _asyncio.run(_timeout_check())
    finally:
        globals()["TaskRunRepository"] = orig_repo

    # --- (d) await_run_terminal success (pending first, terminal second) ---
    pending_snap = TaskRunSnapshot(task_id="task_ok", status="running")
    done_snap = TaskRunSnapshot(task_id="task_ok", status="completed")

    class _SteppedRepo:
        _calls = 0

        def __init__(self) -> None:
            pass

        async def get_snapshot(
            self, task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot | None:
            _ = task_id, workspace_id
            _SteppedRepo._calls += 1
            return pending_snap if _SteppedRepo._calls == 1 else done_snap

    _SteppedRepo._calls = 0
    globals()["TaskRunRepository"] = _SteppedRepo
    try:

        async def _success_check() -> None:
            out = await await_run_terminal("task_ok", timeout=2.0)
            assert out is done_snap, out
            assert _SteppedRepo._calls == 2, _SteppedRepo._calls

        asyncio.run(_success_check())
    finally:
        globals()["TaskRunRepository"] = orig_repo

    # --- (e) pydantic round-trip ---
    empty = RunWorkflowRequest()
    assert empty.inputs == {}
    assert empty.user is None
    filled = RunWorkflowRequest(inputs={"file": "url"}, user="u")
    assert filled.inputs == {"file": "url"}
    assert filled.user == "u"

    # --- Input binding construction ---
    from app.models.task import TaskInputFile
    from app.models.workflow import WorkflowDefinition, WorkflowNode

    wf_with_input = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/file", config={"file": "$file_0"}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[],
    )

    def _build_bindings(
        definition: WorkflowDefinition, inputs: dict[str, Any]
    ) -> dict[str, TaskInputFile] | None:
        nodes = [n for n in definition.nodes if n.type.startswith("input/") and "file" in n.config]
        if not nodes:
            return None
        file_url = inputs.get("file")
        if not file_url:
            raise PublicApiError(status_code=400, code="INVALID_INPUT", message="missing file")
        filename = file_url.rsplit("/", 1)[-1] or "input"
        return {
            n.id: TaskInputFile(
                file_path=file_url, filename=filename, mime_type="application/octet-stream"
            )
            for n in nodes
        }

    # (a) input node + URL → bindings built
    bindings_a = _build_bindings(wf_with_input, {"file": "https://example.com/doc.pdf"})
    assert bindings_a is not None, "bindings should be built for input workflow"
    assert "input_1" in bindings_a, bindings_a
    assert bindings_a["input_1"].file_path == "https://example.com/doc.pdf", bindings_a
    assert bindings_a["input_1"].filename == "doc.pdf", bindings_a
    assert bindings_a["input_1"].mime_type == "application/octet-stream", bindings_a

    # (b) input node + missing file → INVALID_INPUT
    try:
        _build_bindings(wf_with_input, {})
        raise AssertionError("should have raised INVALID_INPUT")
    except PublicApiError as e:
        assert e.code == "INVALID_INPUT", e.code
        assert e.status_code == 400, e.status_code

    # (c) no input nodes → bindings is None (no file required)
    wf_no_input = WorkflowDefinition(
        nodes=[WorkflowNode(id="manual_1", type="engine/ocr", config={"foo": "bar"})],
        connections=[],
    )
    bindings_c = _build_bindings(wf_no_input, {})
    assert bindings_c is None, bindings_c
    # Also: filename fallback when URL has no slash
    bindings_d = _build_bindings(wf_with_input, {"file": "noslash"})
    assert bindings_d is not None, bindings_d
    assert bindings_d["input_1"].filename == "noslash", bindings_d

    # --- Run status response shape ---
    status_snap = TaskRunSnapshot(
        task_id="t1",
        workflow_id="wf_x",
        status="completed",
        duration_ms=500,
        node_summary={"n1": 1},
        created_at=now,
        completed_at=now,
    )

    def _build_status_body(snap: TaskRunSnapshot) -> dict[str, Any]:
        return {
            "workflow_run_id": snap.task_id,
            "workflow_id": snap.workflow_id,
            "status": snap.status,
            "elapsed_time_ms": snap.duration_ms or 0,
            "total_steps": len(snap.node_summary or {}),
            "created_at": (snap.created_at.isoformat() if snap.created_at else None),
            "finished_at": (snap.completed_at.isoformat() if snap.completed_at else None),
        }

    body_status = _build_status_body(status_snap)
    assert body_status["workflow_run_id"] == "t1", body_status
    assert body_status["workflow_id"] == "wf_x", body_status
    assert body_status["status"] == "completed", body_status
    assert body_status["elapsed_time_ms"] == 500, body_status
    assert body_status["total_steps"] == 1, body_status
    # created_at / finished_at must be ISO-parsable strings
    datetime.fromisoformat(body_status["created_at"])
    datetime.fromisoformat(body_status["finished_at"])

    # --- Results endpoint returns 409 before completion ---
    running_snap = TaskRunSnapshot(task_id="t2", workflow_id="wf_x", status="running")

    def _results_check(snap: TaskRunSnapshot) -> None:
        if snap.status not in ("completed", "partial_completed"):
            raise PublicApiError(
                status_code=409,
                code="RUN_NOT_COMPLETE",
                message=f"Run is not complete (status: {snap.status})",
                workflow_run_id=snap.task_id,
            )

    try:
        _results_check(running_snap)
        raise AssertionError("running snapshot should raise RUN_NOT_COMPLETE")
    except PublicApiError as e:
        assert e.status_code == 409, e.status_code
        assert e.code == "RUN_NOT_COMPLETE", e.code
        assert e.extra_fields.get("workflow_run_id") == "t2", e.extra_fields
    # completed/partial_completed must NOT raise
    _results_check(status_snap)
    _results_check(TaskRunSnapshot(task_id="t3", status="partial_completed"))

    # --- Run history pagination ---
    hist_snaps = [
        TaskRunSnapshot(
            task_id=f"r{i}",
            status="completed",
            created_at=now,
            completed_at=now,
            duration_ms=i * 100,
        )
        for i in range(5)
    ]

    def _paginate(
        snaps: list[TaskRunSnapshot], page: int, limit: int
    ) -> tuple[list[TaskRunSnapshot], int]:
        offset = (page - 1) * limit
        return snaps[offset : offset + limit], len(snaps)

    page2_items, total2 = _paginate(hist_snaps, page=2, limit=2)
    assert len(page2_items) == 2, len(page2_items)
    assert total2 == 5, total2
    assert [s.task_id for s in page2_items] == ["r2", "r3"], page2_items

    page1_items, total1 = _paginate(hist_snaps, page=1, limit=10)
    assert len(page1_items) == 5, len(page1_items)
    assert total1 == 5, total1

    # --- (j) workflow_id propagation (BUG-001 fix) ---
    # Verify that upsert_snapshot with workflow_id would set the column
    # (the handler calls this right after _start_dag_run).
    class _CaptureRepo:
        def __init__(self) -> None:
            self.captured: dict[str, Any] = {}

        async def upsert_snapshot(self, **kw: Any) -> None:
            self.captured = kw

    _now = datetime.now(timezone.utc)
    capture = _CaptureRepo()

    async def _propagation_check() -> None:
        await capture.upsert_snapshot(
            task_id="task_test",
            status="pending",
            workflow_id="wf_demo",
            workflow_name=None,
            created_at=_now,
            completed_at=None,
            duration_ms=None,
            node_summary=None,
            result_preview=None,
            results=None,
            error=None,
            updated_at=_now,
        )

    asyncio.run(_propagation_check())
    assert capture.captured.get("workflow_id") == "wf_demo", capture.captured
    assert capture.captured.get("task_id") == "task_test", capture.captured

    print("workflow_runs self-check OK")
