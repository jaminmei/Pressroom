"""Admin API for API Forward usage and trace inspection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.auth import get_authenticated_context
from app.api.workflows import get_workflow_store
from app.db.session import SessionLocal
from app.models.auth import AuthenticatedContext
from app.models.db.workflow_record import WorkflowRecord
from app.repositories.task_run_repository import TaskRunRepository, TaskRunSnapshot
from app.services.api_usage_service import ApiUsageService
from app.services.event_store import EventStore
from app.services.workspace_access import (
    request_workspace_selector,
    resolve_workspace_access,
)
from app.services.workspace_rbac import workspace_rbac_enforced

router = APIRouter(prefix="/api/admin/workflows", tags=["admin-api-usage"])
AuthContextDep = Annotated[AuthenticatedContext, Depends(get_authenticated_context)]


def _ensure_workflow_exists(workflow_id: str) -> None:
    if get_workflow_store().get(workflow_id) is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")


def _require_api_usage_workspace_access(
    workflow_id: str, request: Request, context: AuthenticatedContext
) -> str:
    with SessionLocal() as session:
        resolved = resolve_workspace_access(
            session,
            context=context,
            selector=request_workspace_selector(request, context),
            capability="api_usage.view" if workspace_rbac_enforced() else None,
        )
        workflow = session.scalar(
            select(WorkflowRecord).where(
                (WorkflowRecord.id == workflow_id) | (WorkflowRecord.workflow_key == workflow_id),
                WorkflowRecord.workspace_id == resolved.workspace_id,
            )
        )
    if workflow is None or workflow.workspace_id is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    return str(resolved.workspace_id)


def _resolve_api_usage_workspace_id(
    workflow_id: str,
    request: Request,
    context: AuthenticatedContext,
) -> str:
    return _require_api_usage_workspace_access(workflow_id, request, context)


@router.get("/{workflow_id}/api-usage/summary", response_model=None)
async def get_api_usage_summary(
    workflow_id: str,
    request: Request,
    context: AuthContextDep,
    range: str = Query("7d", pattern="^(24h|7d|30d)$"),  # noqa: A002 - public query name
) -> dict[str, Any]:
    workspace_id = _resolve_api_usage_workspace_id(workflow_id, request, context)
    return await ApiUsageService().summary(workflow_id, range, workspace_id=workspace_id)


@router.get("/{workflow_id}/api-usage/runs", response_model=None)
async def list_api_usage_runs(
    workflow_id: str,
    request: Request,
    context: AuthContextDep,
    range: str = Query("7d", pattern="^(24h|7d|30d)$"),  # noqa: A002
    status: str | None = Query(None, max_length=64),
    key_id: str | None = Query(None, max_length=128),
    endpoint: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    workspace_id = _resolve_api_usage_workspace_id(workflow_id, request, context)
    return await ApiUsageService().list_runs(
        workflow_id=workflow_id,
        range_value=range,
        workspace_id=workspace_id,
        status=status,
        api_key_id=key_id,
        endpoint_kind=endpoint,
        page=page,
        limit=limit,
    )


@router.get("/{workflow_id}/api-usage/runs/{workflow_run_id}/trace", response_model=None)
async def get_api_usage_trace(
    workflow_id: str,
    workflow_run_id: str,
    request: Request,
    context: AuthContextDep,
) -> JSONResponse:
    workspace_id = _resolve_api_usage_workspace_id(workflow_id, request, context)
    service = ApiUsageService()
    invocation = await service.get_invocation_by_run(
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
    )
    if invocation is None:
        raise HTTPException(status_code=404, detail=f"API invocation not found: {workflow_run_id}")

    snapshot = await TaskRunRepository().get_snapshot(workflow_run_id, workspace_id=workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run snapshot not found: {workflow_run_id}")

    workflow_payload = _resolve_workflow_payload(workflow_id, snapshot, workspace_id)
    events = EventStore().get_events(workflow_run_id)
    node_status = _build_node_status(workflow_payload, events)

    return JSONResponse(
        status_code=200,
        content={
            "workflow_id": workflow_id,
            "workflow_run_id": workflow_run_id,
            "status": snapshot.status or invocation.workflow_status,
            "created_at": snapshot.created_at.isoformat()
            if snapshot.created_at
            else invocation.created_at.isoformat(),
            "completed_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
            "duration_ms": snapshot.duration_ms,
            "endpoint_kind": invocation.endpoint_kind,
            "api_key_prefix": invocation.api_key_prefix,
            "input_metadata": invocation.input_metadata,
            "workflow": workflow_payload,
            "node_status": node_status,
            "event_count": len(events),
            "result_preview": snapshot.result_preview,
        },
    )


def _resolve_workflow_payload(
    workflow_id: str,
    snapshot: TaskRunSnapshot,
    workspace_id: str | None,
) -> dict[str, Any] | None:
    if snapshot.workflow:
        return snapshot.workflow
    workflow = get_workflow_store().get(workflow_id, workspace_id=workspace_id)
    if workflow is None:
        return None
    return workflow.definition.model_dump(mode="json")


def _build_node_status(workflow: dict[str, Any] | None, events: list[Any]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        timestamp = datetime.fromtimestamp(float(event.timestamp), tz=UTC).isoformat()
        status = _event_to_status(event.event_type)
        item = {
            "node_id": event.node_id,
            "node_type": event.node_type,
            "status": status,
            "started_at": timestamp if status == "running" else None,
            "completed_at": timestamp if status in {"completed", "failed", "skipped"} else None,
            "error": event.error.message if getattr(event, "error", None) else None,
        }
        previous = latest.get(event.node_id)
        if previous:
            if previous.get("started_at") and not item.get("started_at"):
                item["started_at"] = previous["started_at"]
        latest[event.node_id] = item

    if workflow and isinstance(workflow.get("nodes"), list):
        ordered: list[dict[str, Any]] = []
        for node in workflow["nodes"]:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            ordered.append(
                latest.get(
                    node_id,
                    {
                        "node_id": node_id,
                        "node_type": str(node.get("type", "")),
                        "status": "pending",
                        "started_at": None,
                        "completed_at": None,
                        "error": None,
                    },
                )
            )
        return ordered

    return list(latest.values())


def _event_to_status(event_type: str) -> str:
    if event_type == "started":
        return "running"
    if event_type == "completed":
        return "completed"
    if event_type == "failed":
        return "failed"
    if event_type == "skipped":
        return "skipped"
    return event_type
