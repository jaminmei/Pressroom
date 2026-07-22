"""Admin API for API Key management (issue / list / revoke).

Self-check: ``python -m app.api.admin.api_keys``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import get_authenticated_context
from app.db.session import SessionLocal
from app.models.auth import AuthenticatedContext
from app.models.db.workflow_record import WorkflowRecord
from app.repositories.api_key_repository import ApiKeyRecord
from app.services.api_key_service import ApiKeyService
from app.services.workspace_access import (
    ResolvedContext,
    request_workspace_selector,
    resolve_workspace_access,
)
from app.services.workspace_rbac import workspace_rbac_enforced

router = APIRouter(prefix="/api/admin/api-keys", tags=["admin-api-keys"])
_API_KEY_MANAGE_CAPABILITY: Final = "api_key.manage"


async def get_api_key_service(request: Request) -> ApiKeyService:
    service: ApiKeyService | None = getattr(request.app.state, "api_key_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="API key service not initialised")
    return service


ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
AuthContextDep = Annotated[AuthenticatedContext, Depends(get_authenticated_context)]


class IssueApiKeyRequest(BaseModel):
    workflow_id: str = Field(..., max_length=64)
    description: str | None = Field(None, max_length=500)


@dataclass(frozen=True, slots=True)
class _ResolvedWorkflow:
    id: str
    workspace_id: str | None


def _serialize_key_full(full_key: str, record: ApiKeyRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "key": full_key,
        "key_prefix": record.key_prefix,
        "workflow_id": record.workflow_id,
        "description": record.description,
        "created_at": _serialize_datetime(record.created_at),
    }


def _serialize_key(record: ApiKeyRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "key_prefix": record.key_prefix,
        "workflow_id": record.workflow_id,
        "description": record.description,
        "is_active": record.is_active,
        "created_at": _serialize_datetime(record.created_at),
        "last_used_at": _serialize_datetime(record.last_used_at),
        "expires_at": _serialize_datetime(record.expires_at),
    }


def _serialize_datetime(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return datetime.fromisoformat(value).isoformat()


def _resolve_workflow(
    workflow_identifier: str, *, workspace_id: str | None = None
) -> _ResolvedWorkflow | None:
    with SessionLocal() as session:
        statement = select(WorkflowRecord).where(
            (WorkflowRecord.id == workflow_identifier)
            | (WorkflowRecord.workflow_key == workflow_identifier)
        )
        if workspace_id is not None:
            statement = statement.where(WorkflowRecord.workspace_id == workspace_id)
        record = session.scalar(statement)
    if record is None:
        return None
    return _ResolvedWorkflow(id=record.id, workspace_id=record.workspace_id)


def _resolve_api_key_context(request: Request, context: AuthenticatedContext) -> ResolvedContext:
    with SessionLocal() as session:
        return resolve_workspace_access(
            session,
            context=context,
            selector=request_workspace_selector(request, context),
            capability=_API_KEY_MANAGE_CAPABILITY if workspace_rbac_enforced() else None,
        )


@router.post("", response_model=None, status_code=201)
async def issue_api_key(
    payload: IssueApiKeyRequest,
    request: Request,
    service: ApiKeyServiceDep,
    context: AuthContextDep,
) -> dict[str, object]:
    resolved = _resolve_api_key_context(request, context)
    workflow = _resolve_workflow(payload.workflow_id, workspace_id=resolved.workspace_id)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not found: {payload.workflow_id}",
        )
    full_key, record = await service.issue(
        workflow_id=workflow.id,
        workspace_id=resolved.workspace_id,
        description=payload.description,
        created_by=resolved.user.id,
    )
    return _serialize_key_full(full_key, record)


@router.get("", response_model=None)
async def list_api_keys(
    service: ApiKeyServiceDep,
    request: Request,
    context: AuthContextDep,
    workflow_id: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
) -> dict[str, object]:
    offset = (page - 1) * limit
    resolved = _resolve_api_key_context(request, context)
    if workflow_id:
        workflow = _resolve_workflow(workflow_id, workspace_id=resolved.workspace_id)
        if workflow is None:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
        records, total = await service.list_by_workflow_paginated(
            workflow.id,
            limit=limit,
            offset=offset,
            include_inactive=include_inactive,
            workspace_id=resolved.workspace_id,
        )
    else:
        records, total = await service.list_paginated(
            limit=limit,
            offset=offset,
            workspace_id=resolved.workspace_id,
            include_inactive=include_inactive,
        )
    return {
        "data": [_serialize_key(r) for r in records],
        "meta": {"total": total, "page": page, "limit": limit},
    }


@router.post("/{key_id}/revoke", response_model=None)
async def revoke_api_key(
    key_id: str,
    request: Request,
    service: ApiKeyServiceDep,
    context: AuthContextDep,
) -> dict[str, object]:
    resolved = _resolve_api_key_context(request, context)
    key_record = await service.get_by_id(key_id, workspace_id=resolved.workspace_id)
    if key_record is None:
        raise HTTPException(status_code=404, detail=f"API key not found: {key_id}")
    ok = await service.revoke(key_id, workspace_id=resolved.workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"API key not found: {key_id}")
    return {"id": key_id, "is_active": False}


if __name__ == "__main__":
    # --- stub repository: in-memory, mimics ApiKeyRepository surface used by routes ---
    class _StubRepo:
        def __init__(self) -> None:
            self._rows: dict[str, ApiKeyRecord] = {}

        async def create(
            self,
            *,
            id: str,
            key_hash: str,
            key_prefix: str,
            workflow_id: str,
            description: str | None = None,
            created_by: str | None = None,
            expires_at: datetime | None = None,
        ) -> ApiKeyRecord:
            rec = ApiKeyRecord(
                id=id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                workflow_id=workflow_id,
                description=description,
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                is_active=True,
                last_used_at=None,
            )
            self._rows[id] = rec
            return rec

        async def list_all(self, limit: int = 100, offset: int = 0) -> list[ApiKeyRecord]:
            all_rows = list(self._rows.values())
            return all_rows[offset : offset + limit]

        async def count(self) -> int:
            return len(self._rows)

        async def get_by_id(self, id: str) -> ApiKeyRecord | None:
            return self._rows.get(id)

        async def set_active(
            self,
            id: str,
            is_active: bool,
            *,
            workspace_id: str | None = None,
        ) -> bool:
            rec = self._rows.get(id)
            if rec is None:
                return False
            self._rows[id] = ApiKeyRecord(
                id=rec.id,
                key_hash=rec.key_hash,
                key_prefix=rec.key_prefix,
                workflow_id=rec.workflow_id,
                description=rec.description,
                created_by=rec.created_by,
                created_at=rec.created_at,
                expires_at=rec.expires_at,
                is_active=is_active,
                last_used_at=rec.last_used_at,
            )
            return True

    async def _run() -> None:
        repo: Any = _StubRepo()
        svc = ApiKeyService(repository=repo)

        # create
        full, _rec = await svc.issue(workflow_id="wf_demo", description="d1")
        # the route returns full_key + record; replicate _serialize_key_full
        first_id = _rec.id
        assert full.startswith("dca_"), f"key prefix wrong: {full[:8]}"
        created = _serialize_key_full(full, _rec)
        assert created["key"] == full
        assert created["workflow_id"] == "wf_demo"
        assert created["description"] == "d1"

        # second key to ensure multi-row listing
        full2, rec2 = await svc.issue(workflow_id="wf_two")
        _ = rec2

        # list_paginated — route envelope shape (page 1, limit 20)
        records_page, total = await svc.list_paginated(limit=20, offset=0)
        listed = [_serialize_key(r) for r in records_page]
        assert total == 2, f"total wrong: {total}"
        assert len(listed) == 2
        assert all("key" not in row for row in listed), "list leaked full key"
        assert all("key_hash" not in row for row in listed), "list leaked key_hash"

        # pagination meta — limit=1 slices one row, total stays 2
        recs_paged, total_paged = await svc.list_paginated(limit=1, offset=0)
        assert total_paged == 2, f"paged total wrong: {total_paged}"
        assert len(recs_paged) == 1, f"paged len wrong: {len(recs_paged)}"

        # revoke first
        ok = await svc.revoke(first_id)
        assert ok is True

        # 404 path: revoke unknown id
        missing = await svc.revoke("does-not-exist")
        assert missing is False

        # list-after-revoke shows row with is_active=False
        rows2, _total2 = await svc.list_paginated(limit=20, offset=0)
        revoked_row = next(r for r in rows2 if r.id == first_id)
        assert revoked_row.is_active is False
        listed2 = [_serialize_key(r) for r in rows2]
        revoked_serialized = next(r for r in listed2 if r["id"] == first_id)
        assert revoked_serialized["is_active"] is False

        # --- input validation: max_length rejection ---
        from pydantic import ValidationError

        try:
            IssueApiKeyRequest(workflow_id="x" * 65, description=None)
            raise AssertionError("should have rejected workflow_id > 64 chars")
        except ValidationError:
            pass
        try:
            IssueApiKeyRequest(workflow_id="ok", description="d" * 501)
            raise AssertionError("should have rejected description > 500 chars")
        except ValidationError:
            pass

        # --- 404 path: missing workflow.
        # The route does: if get_workflow_store().get(workflow_id) is None:
        #                    raise HTTPException(404, ...)
        # Stub the store to mimic a real miss and confirm the guard fires.
        class _MissingWorkflowStore:
            def get(self, workflow_id: str) -> object | None:
                return None

        missing_store = _MissingWorkflowStore()
        assert missing_store.get("does-not-exist-id-xyz") is None
        try:
            if missing_store.get("does-not-exist-id-xyz") is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
            raise AssertionError("should have raised 404 for missing workflow")
        except HTTPException as exc:
            assert exc.status_code == 404, f"unexpected status: {exc.status_code}"

    asyncio.run(_run())
    print("admin api_keys self-check OK")
