from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import ResolvedContext, require_workspace_capability
from app.api.error_response import error_response as build_error_response
from app.errors import ErrorCode
from app.models.workflow import Workflow, WorkflowActor, WorkflowDefinition
from app.services.database_workflow_store import DatabaseWorkflowStore, WorkflowVersionConflictError
from app.services.node_registry import NodeRegistryService
from app.services.topological_sort import build_execution_plan
from app.services.workflow_execution import PersistedWorkflowExecution
from app.services.workflow_utils import normalize_workflow_definition_for_ingress
from app.services.workflow_validator import ValidationIssue, ValidationWarning, WorkflowValidator
from app.utils.workflow_hash import compute_dag_hash

router = APIRouter()


class WorkflowCreateRequest(BaseModel):
    name: str | None = None
    definition: WorkflowDefinition


class WorkflowSaveRequest(BaseModel):
    workflow_id: str | None = None
    workflow_key: str | None = None
    base_version: int | None = Field(default=None, ge=1)
    name: str | None = None
    description: str | None = None
    definition: WorkflowDefinition


class WorkflowMetadataUpdateRequest(BaseModel):
    name: str
    description: str | None = None


class WorkflowExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int | None = Field(default=None, ge=1)
    file_ids: list[str] = Field(default_factory=list)
    run_name: str | None = Field(default=None, max_length=200)


class WorkflowRestoreRequest(BaseModel):
    version: int = Field(ge=1)


class WorkflowImportData(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: WorkflowDefinition


class WorkflowImportRequest(BaseModel):
    format_version: str
    exported_at: datetime | None = None
    workflow: WorkflowImportData


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    return build_error_response(
        status_code=status_code,
        error_code=code,
        message=message,
        details=details,
    )


@lru_cache
def get_workflow_store() -> DatabaseWorkflowStore:
    return DatabaseWorkflowStore()


@lru_cache
def _node_registry() -> NodeRegistryService:
    return NodeRegistryService()


def get_workflow_validator(request: Request) -> WorkflowValidator:
    """Build a validator from the provider store owned by this request's app."""
    provider_store = getattr(request.app.state, "provider_store", None)
    return WorkflowValidator(node_registry=_node_registry(), provider_store=provider_store)


def _issue_payload(issue: ValidationIssue) -> dict[str, object]:
    return {
        "code": issue.code,
        "message": issue.message,
        "details": issue.details,
        "severity": issue.severity,
        "node_id": issue.node_id,
        "field": issue.field,
    }


def _warning_payload(warning: ValidationWarning) -> dict[str, object]:
    return {
        "code": warning.code,
        "severity": warning.severity,
        "node_id": warning.node_id,
        "message": warning.message,
        "model": warning.model,
    }


def _workflow_actor(context: ResolvedContext) -> WorkflowActor:
    return WorkflowActor(
        user_id=context.user.id,
        email=context.user.email,
        name=context.user.name,
    )


def _active_workspace_id(context: ResolvedContext) -> str:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return context.workspace_id


def _actor_payload(actor: WorkflowActor | None) -> dict[str, object] | None:
    if actor is None:
        return None
    return {
        "user_id": actor.user_id,
        "email": actor.email,
        "name": actor.name,
    }


def _serialize_workflow_summary(workflow: Workflow) -> dict[str, object]:
    return {
        "id": workflow.id,
        "workflow_key": workflow.workflow_key,
        "name": workflow.name,
        "description": workflow.description,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "published_version": workflow.published_version,
        "latest_version": workflow.latest_version,
        "created_by": _actor_payload(workflow.created_by),
        "last_saved_by": _actor_payload(workflow.last_saved_by),
    }


def _serialize_workflow_detail(workflow: Workflow) -> dict[str, object]:
    payload = workflow.model_dump(mode="json")
    payload["created_by"] = _actor_payload(workflow.created_by)
    payload["last_saved_by"] = _actor_payload(workflow.last_saved_by)
    return payload


@router.post("/workflows/validate", response_model=None)
async def validate_workflow(
    payload: WorkflowDefinition,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))],
) -> JSONResponse:
    validator = get_workflow_validator(request)
    static_result = validator.validate(payload, workspace_id=ctx.workspace_id)
    dynamic_warnings = validator.validate_dynamic(payload)
    health_warnings = await validator.check_engine_health(payload)

    return JSONResponse(
        status_code=200,
        content={
            "static": {
                "valid": static_result.valid,
                "errors": [_issue_payload(e) for e in static_result.errors],
                "warnings": [_issue_payload(w) for w in static_result.warnings],
            },
            "dynamic": {
                "warnings": [_warning_payload(w) for w in dynamic_warnings],
            },
            "provider_health": {
                "checked": True,
                "warnings": [_warning_payload(w) for w in health_warnings],
            },
        },
    )


@router.post("/workflows", response_model=None)
async def create_workflow(
    payload: WorkflowCreateRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))],
) -> JSONResponse:
    validator = get_workflow_validator(request)
    result = validator.validate(payload.definition, workspace_id=ctx.workspace_id)

    if result.errors:
        return _error_response(
            400,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={
                "errors": [_issue_payload(err) for err in result.errors],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
        )

    workflow = get_workflow_store().create(
        name=payload.name,
        definition=payload.definition,
        actor=_workflow_actor(ctx),
        workspace_id=ctx.workspace_id,
    )
    plan = build_execution_plan(payload.definition)

    return JSONResponse(
        status_code=201,
        content={
            "workflow_id": workflow.id,
            "workflow_key": workflow.workflow_key,
            "validation": {
                "valid": True,
                "errors": [],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
            "dynamic": {
                "warnings": [
                    _warning_payload(w) for w in validator.validate_dynamic(payload.definition)
                ],
            },
            "execution_plan": {
                "total_nodes": plan.total_nodes,
                "execution_order": plan.execution_order,
                "parallel_groups": plan.parallel_groups,
                "estimated_duration_seconds": plan.estimated_duration_seconds,
            },
        },
    )


# DEPRECATED: Use POST /workflows/publish for the unified publish flow.
# This endpoint is retained for backward compatibility but will be removed.
@router.post("/workflows/save", response_model=None)
async def save_workflow(
    payload: WorkflowSaveRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))],
) -> JSONResponse:
    normalized_definition = normalize_workflow_definition_for_ingress(payload.definition)
    validator = get_workflow_validator(request)
    result = validator.validate(normalized_definition, workspace_id=ctx.workspace_id)
    if result.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={
                "errors": [_issue_payload(err) for err in result.errors],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
        )

    store = get_workflow_store()
    try:
        workflow = store.save(
            workflow_id=payload.workflow_id,
            workflow_key=payload.workflow_key,
            base_version=payload.base_version,
            name=payload.name,
            description=payload.description,
            definition=normalized_definition,
            actor=_workflow_actor(ctx),
            workspace_id=ctx.workspace_id,
        )
    except KeyError:
        workflow_id = payload.workflow_id or ""
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )
    except WorkflowVersionConflictError as exc:
        return _error_response(
            409,
            ErrorCode.WORKFLOW_VERSION_CONFLICT.value,
            "目前 workflow 已有較新的 shared saved version，請先重新整理或改用 Save As。",
            details={
                "workflow_id": exc.workflow_id,
                "workflow_key": exc.workflow_key,
                "base_version": exc.base_version,
                "latest_version": exc.latest_version,
                "current_name": exc.current_name,
                "last_saved_by": _actor_payload(exc.last_saved_by),
                "updated_at": exc.updated_at.isoformat(),
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                **_serialize_workflow_summary(workflow),
                "base_version": payload.base_version,
            },
            "warnings": [_issue_payload(warning) for warning in result.warnings],
            "dynamic": {
                "warnings": [
                    _warning_payload(w) for w in validator.validate_dynamic(normalized_definition)
                ],
            },
        },
    )


@router.get("/workflows", response_model=None)
async def list_workflows(
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.view"))],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    sort: str = Query(default="updated_at:desc"),
    q: str | None = Query(default=None),
) -> JSONResponse:
    sort_by, _, sort_order = sort.partition(":")
    sort_field = sort_by or "updated_at"
    order = sort_order or "desc"

    workflows, total = get_workflow_store().list_paginated(
        page=page,
        limit=limit,
        sort_by=sort_field,
        sort_order=order,
        query=q,
        workspace_id=ctx.workspace_id,
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": [_serialize_workflow_summary(workflow) for workflow in workflows],
            "meta": {
                "total": total,
                "page": page,
                "limit": limit,
            },
        },
    )


@router.post("/workflows/import", response_model=None)
async def import_workflow(
    payload: WorkflowImportRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))],
) -> JSONResponse:
    if payload.format_version != "1.0":
        return _error_response(
            422,
            "UNSUPPORTED_FORMAT_VERSION",
            f"不支援的 format_version：{payload.format_version}",
        )

    normalized_definition = normalize_workflow_definition_for_ingress(payload.workflow.definition)
    validator = get_workflow_validator(request)
    result = validator.validate(normalized_definition, workspace_id=ctx.workspace_id)
    if result.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={
                "errors": [_issue_payload(err) for err in result.errors],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
        )

    workflow = get_workflow_store().create(
        name=payload.workflow.name,
        description=payload.workflow.description,
        definition=normalized_definition,
        actor=_workflow_actor(ctx),
        workspace_id=ctx.workspace_id,
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": _serialize_workflow_summary(workflow),
            "warnings": [_issue_payload(warning) for warning in result.warnings],
            "dynamic": {
                "warnings": [
                    _warning_payload(w) for w in validator.validate_dynamic(normalized_definition)
                ],
            },
        },
    )


@router.get("/workflows/{workflow_id}/export", response_model=None)
async def export_workflow(
    workflow_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.view"))],
) -> JSONResponse:
    workflow = get_workflow_store().get(workflow_id, workspace_id=ctx.workspace_id)
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    payload = {
        "format_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workflow": {
            "workflow_key": workflow.workflow_key,
            "name": workflow.name,
            "description": workflow.description,
            "definition": workflow.definition.model_dump(mode="json"),
        },
    }

    return JSONResponse(
        status_code=200,
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{workflow.id}.json"'},
    )


@router.get("/workflows/{workflow_id}", response_model=None)
async def get_workflow(
    workflow_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.view"))],
) -> JSONResponse:
    store = get_workflow_store()
    workflow = store.get(workflow_id, workspace_id=ctx.workspace_id)
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    workflow = workflow.model_copy(
        update={"definition": normalize_workflow_definition_for_ingress(workflow.definition)}
    )

    return JSONResponse(status_code=200, content=_serialize_workflow_detail(workflow))


@router.patch("/workflows/{workflow_id}", response_model=None)
async def update_workflow_metadata(
    workflow_id: str,
    payload: WorkflowMetadataUpdateRequest,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))],
) -> JSONResponse:
    normalized_name = payload.name.strip()
    if not normalized_name:
        return _error_response(
            400,
            "WORKFLOW_METADATA_INVALID",
            "Workflow 名稱不可為空",
        )

    if "description" in payload.model_fields_set:
        normalized_description = (
            payload.description.strip() if isinstance(payload.description, str) else None
        )
        workflow = get_workflow_store().update(
            workflow_id,
            name=normalized_name,
            description=normalized_description or None,
            actor=_workflow_actor(ctx),
            workspace_id=ctx.workspace_id,
        )
    else:
        workflow = get_workflow_store().update(
            workflow_id,
            name=normalized_name,
            actor=_workflow_actor(ctx),
            workspace_id=ctx.workspace_id,
        )
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": _serialize_workflow_summary(workflow),
        },
    )


@router.get("/workflows/{workflow_key}/versions", response_model=None)
async def list_workflow_versions(
    workflow_key: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.view"))],
) -> JSONResponse:
    store = get_workflow_store()
    workflow = store.get(workflow_key, workspace_id=ctx.workspace_id)
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_key}",
        )

    versions = store.list_versions(workflow_key, workspace_id=ctx.workspace_id)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": [version.model_dump(mode="json") for version in versions],
            "meta": {"total": len(versions)},
        },
    )


@router.get("/workflows/{workflow_id}/versions/{version}", response_model=None)
async def get_workflow_version(
    workflow_id: str,
    version: int,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.view"))],
) -> JSONResponse:
    store = get_workflow_store()
    snapshot = store.get_version(workflow_id, version, workspace_id=ctx.workspace_id)
    if snapshot is None:
        workflow = store.get(workflow_id, workspace_id=ctx.workspace_id)
        if workflow is None:
            return _error_response(
                404,
                ErrorCode.WORKFLOW_NOT_FOUND.value,
                f"找不到 Workflow：{workflow_id}",
            )
        return _error_response(404, "WORKFLOW_VERSION_NOT_FOUND", f"找不到版本：v{version}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": snapshot.model_dump(mode="json"),
        },
    )


# DEPRECATED: Use POST /workflows/publish with workflow_id for the unified publish flow.
# This endpoint only sets published_version without dag_hash computation.
@router.post("/workflows/{workflow_id}/publish", response_model=None)
async def publish_workflow(
    workflow_id: str,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    store = get_workflow_store()
    workflow = store.get(workflow_id, workspace_id=ctx.workspace_id)
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    normalized_definition = normalize_workflow_definition_for_ingress(workflow.definition)
    result = get_workflow_validator(request).validate_for_publish(
        normalized_definition,
        workspace_id=ctx.workspace_id,
    )
    if result.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={
                "errors": [_issue_payload(error) for error in result.errors],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
        )

    snapshot = store.publish(workflow_id, workspace_id=ctx.workspace_id)
    if snapshot is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    workflow = store.get(workflow_id, workspace_id=ctx.workspace_id)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "workflow_id": workflow_id,
                "workflow_key": workflow.workflow_key if workflow else None,
                "version": snapshot.version,
                "published_at": snapshot.created_at.isoformat(),
                "published_version": workflow.published_version if workflow else snapshot.version,
            },
        },
    )


@router.post("/workflows/{workflow_key}/restore/{version}", response_model=None)
async def restore_workflow_version_by_key(
    workflow_key: str,
    version: int,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    store = get_workflow_store()
    restored = store.restore(
        workflow_key,
        version=version,
        actor=_workflow_actor(ctx),
        workspace_id=ctx.workspace_id,
    )
    if restored is None:
        workflow = store.get(workflow_key, workspace_id=ctx.workspace_id)
        if workflow is None:
            return _error_response(
                404,
                ErrorCode.WORKFLOW_NOT_FOUND.value,
                f"找不到 Workflow：{workflow_key}",
            )
        return _error_response(404, "WORKFLOW_VERSION_NOT_FOUND", f"找不到版本：v{version}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "workflow_id": restored.id,
                "workflow_key": restored.workflow_key,
                "restored_version": version,
                "updated_at": restored.updated_at.isoformat(),
                "latest_version": restored.latest_version,
                "last_saved_by": _actor_payload(restored.last_saved_by),
            },
        },
    )


@router.post("/workflows/{workflow_id}/restore", response_model=None)
async def restore_workflow(
    workflow_id: str,
    payload: WorkflowRestoreRequest,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    store = get_workflow_store()
    restored = store.restore(
        workflow_id,
        version=payload.version,
        actor=_workflow_actor(ctx),
        workspace_id=ctx.workspace_id,
    )
    if restored is None:
        workflow = store.get(workflow_id, workspace_id=ctx.workspace_id)
        if workflow is None:
            return _error_response(
                404,
                ErrorCode.WORKFLOW_NOT_FOUND.value,
                f"找不到 Workflow：{workflow_id}",
            )
        return _error_response(404, "WORKFLOW_VERSION_NOT_FOUND", f"找不到版本：v{payload.version}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "workflow_id": workflow_id,
                "workflow_key": restored.workflow_key,
                "restored_version": payload.version,
                "updated_at": restored.updated_at.isoformat(),
                "latest_version": restored.latest_version,
                "last_saved_by": _actor_payload(restored.last_saved_by),
            },
        },
    )


@router.delete("/workflows/{workflow_id}", response_model=None)
async def delete_workflow(
    workflow_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    deleted = get_workflow_store().delete(workflow_id, workspace_id=ctx.workspace_id)
    if not deleted:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    return JSONResponse(status_code=200, content={"success": True})


@router.post("/workflows/{workflow_id}/execute", response_model=None)
async def execute_workflow(
    workflow_id: str,
    payload: WorkflowExecuteRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.run"))],
) -> JSONResponse:
    workflow = get_workflow_store().get(workflow_id, workspace_id=ctx.workspace_id)
    if workflow is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{workflow_id}",
        )

    definition = workflow.definition
    if payload.version is not None:
        snapshot = get_workflow_store().get_version(
            workflow_id,
            payload.version,
            workspace_id=ctx.workspace_id,
        )
        if snapshot is None:
            return _error_response(
                404,
                "WORKFLOW_VERSION_NOT_FOUND",
                f"找不到版本：v{payload.version}",
            )
        definition = snapshot.definition

    validation = get_workflow_validator(request).validate(
        definition,
        workspace_id=ctx.workspace_id,
    )
    if validation.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={"errors": [_issue_payload(error) for error in validation.errors]},
        )

    try:
        context = await request.app.state.workflow_execution.execute(
            definition,
            PersistedWorkflowExecution(
                file_ids=payload.file_ids,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                run_name=payload.run_name,
                workspace_id=_active_workspace_id(ctx),
                requested_by_user_id=ctx.user.id,
            ),
        )
    except ValueError as exc:
        return _error_response(400, "WORKFLOW_VALIDATION_ERROR", str(exc))

    return JSONResponse(
        status_code=202,
        content={
            "task_id": context.task_id,
            "workflow_id": workflow_id,
            "status": context.status.value,
            "created_at": context.created_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Workflow lifecycle: publish & lookup
# ---------------------------------------------------------------------------


class WorkflowUnifiedPublishRequest(BaseModel):
    workflow_id: str | None = None
    name: str | None = None
    description: str | None = None
    definition: WorkflowDefinition
    base_version: int | None = Field(default=None, ge=1)


class WorkflowPublishAsRequest(BaseModel):
    workflow_id: str
    name: str
    description: str | None = None


def _compute_definition_dag_hash(definition: WorkflowDefinition) -> str:
    nodes = [{"id": n.id, "type": n.type} for n in definition.nodes]
    edges = [
        {
            "source": c.source,
            "target": c.target,
            "sourceHandle": c.source_port,
            "targetHandle": c.target_port,
        }
        for c in definition.connections
    ]
    node_configs = {n.id: n.config for n in definition.nodes}
    return compute_dag_hash(nodes, edges, node_configs)


@router.post("/workflows/publish", response_model=None)
async def publish_workflow_unified(
    payload: WorkflowUnifiedPublishRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    normalized_definition = normalize_workflow_definition_for_ingress(payload.definition)
    validator = get_workflow_validator(request)
    result = validator.validate_for_publish(normalized_definition, workspace_id=ctx.workspace_id)
    if result.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗",
            details={
                "errors": [_issue_payload(err) for err in result.errors],
                "warnings": [_issue_payload(warning) for warning in result.warnings],
            },
        )

    store = get_workflow_store()
    dag_hash = _compute_definition_dag_hash(normalized_definition)
    actor = _workflow_actor(ctx)

    if payload.workflow_id is None:
        # --- New workflow ---
        name = payload.name or "Untitled Workflow"
        workflow = store.publish_new_workflow(
            name=name,
            description=payload.description,
            definition=normalized_definition,
            dag_hash=dag_hash,
            actor=actor,
            workspace_id=ctx.workspace_id,
        )

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "data": {
                    "workflow_id": workflow.id,
                    "workflow_key": workflow.workflow_key,
                    "version": 1,
                    "dag_hash": dag_hash,
                },
            },
        )

    # --- Existing workflow ---
    # Check for same-workflow dedup
    duplicate_version = store.find_duplicate_dag_hash(
        payload.workflow_id,
        dag_hash,
        workspace_id=ctx.workspace_id,
    )
    if duplicate_version is not None:
        return _error_response(
            409,
            "DUPLICATE_DAG_HASH",
            "A version with the same DAG structure already exists for this workflow.",
            details={"duplicate_of_version": duplicate_version},
        )

    try:
        workflow = store.publish_next_version(
            payload.workflow_id,
            name=payload.name,
            description=payload.description,
            definition=normalized_definition,
            dag_hash=dag_hash,
            base_version=payload.base_version,
            actor=actor,
            workspace_id=ctx.workspace_id,
        )
    except KeyError:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{payload.workflow_id}",
        )
    except WorkflowVersionConflictError as exc:
        return _error_response(
            409,
            ErrorCode.WORKFLOW_VERSION_CONFLICT.value,
            "目前 workflow 已有較新的 shared saved version，請先重新整理或改用 Save As。",
            details={
                "workflow_id": exc.workflow_id,
                "workflow_key": exc.workflow_key,
                "base_version": exc.base_version,
                "latest_version": exc.latest_version,
                "current_name": exc.current_name,
                "last_saved_by": _actor_payload(exc.last_saved_by),
                "updated_at": exc.updated_at.isoformat(),
            },
        )

    new_version = workflow.latest_version

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "workflow_id": payload.workflow_id,
                "workflow_key": workflow.workflow_key,
                "version": new_version,
                "dag_hash": dag_hash,
                "duplicate_of_version": None,
            },
        },
    )


@router.post("/workflows/publish-as", response_model=None)
async def publish_workflow_as(
    payload: WorkflowPublishAsRequest,
    request: Request,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.publish"))],
) -> JSONResponse:
    store = get_workflow_store()
    existing = store.get(payload.workflow_id, workspace_id=ctx.workspace_id)
    if existing is None:
        return _error_response(
            404,
            ErrorCode.WORKFLOW_NOT_FOUND.value,
            f"找不到 Workflow：{payload.workflow_id}",
        )

    actor = _workflow_actor(ctx)
    definition = existing.definition

    normalized_definition = normalize_workflow_definition_for_ingress(definition)
    validator = get_workflow_validator(request)
    result = validator.validate_for_publish(normalized_definition, workspace_id=ctx.workspace_id)
    if result.errors:
        return _error_response(
            422,
            "WORKFLOW_VALIDATION_ERROR",
            "Workflow 定義驗證失敗（從 source workflow 繼承的定義已失效）",
            details={
                "errors": [_issue_payload(err) for err in result.errors],
            },
        )

    dag_hash = _compute_definition_dag_hash(normalized_definition)

    new_workflow = store.publish_new_workflow(
        name=payload.name,
        description=payload.description,
        definition=normalized_definition,
        dag_hash=dag_hash,
        actor=actor,
        workspace_id=ctx.workspace_id,
    )

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "data": {
                "workflow_id": new_workflow.id,
                "workflow_key": new_workflow.workflow_key,
                "version": 1,
                "dag_hash": dag_hash,
                "source_workflow_id": payload.workflow_id,
            },
            "warnings": [_issue_payload(warning) for warning in result.warnings],
        },
    )
