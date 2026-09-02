from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, cast
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.auth import require_workspace_capability
from app.api.task_helpers import validate_upload
from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.errors.error_response import CANONICAL_ERROR_RESPONSES
from app.models.file_api import (
    FileDeletionImpactResponse,
    FileListResponse,
    FileResourceResponse,
    FileUploadResponse,
)
from app.services.file_store import FileQuotaExceededError, FileStore, UploadedFileRecord
from app.services.workspace_access import ResolvedContext
from app.storage.local import get_storage

router = APIRouter(responses=CANONICAL_ERROR_RESPONSES)


@lru_cache
def get_file_store() -> FileStore:
    return FileStore()


def _serialize(record: UploadedFileRecord) -> FileResourceResponse:
    return FileResourceResponse(
        file_id=record.file_id,
        filename=record.filename,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        status=cast(Literal["active", "deleted", "cleanup_failed"], record.status),
        uploaded_by_user_id=str(record.uploaded_by_user_id),
        created_at=record.created_at,
        updated_at=record.updated_at,
        deleted_at=record.deleted_at,
    )


def _workspace_id(ctx: ResolvedContext) -> str:
    if ctx.workspace_id is None:
        raise AppError(ErrorCode.WORKSPACE_NOT_FOUND, "Workspace context is required")
    return ctx.workspace_id


def _storage_key(storage_path: str, storage_root: str | Path) -> str:
    root = Path(storage_root).resolve()
    resolved = Path(storage_path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Stored file escaped the storage root") from exc


async def _persist_upload(
    file: UploadFile,
    ctx: ResolvedContext,
) -> UploadedFileRecord | JSONResponse:
    settings = get_settings()
    content = await validate_upload(file, settings)
    if isinstance(content, JSONResponse):
        return content

    mime_type = (file.content_type or "").lower()
    workspace_id = _workspace_id(ctx)
    store = get_file_store()
    store.purge_expired_deleted_metadata(
        retention_days=settings.workspace_file_deleted_retention_days,
    )
    file_id = f"file_{uuid4()}"
    raw_filename = (file.filename or "upload.bin").replace("\\", "/")
    filename = Path(raw_filename).name
    storage = get_storage()
    storage_path = await storage.save_file(file_id, "original", filename, content)
    record = UploadedFileRecord(
        file_id=file_id,
        storage_path=_storage_key(storage_path, storage.storage_root),
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(content),
        workspace_id=workspace_id,
        uploaded_by_user_id=ctx.user.id,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    try:
        store.put_with_quota(record, quota_bytes=settings.workspace_file_quota_bytes)
    except FileQuotaExceededError as exc:
        await storage.delete_file(record.storage_path)
        raise AppError(
            ErrorCode.FILE_QUOTA_EXCEEDED,
            "Workspace File quota would be exceeded",
            details={
                "quota_bytes": exc.quota_bytes,
                "used_bytes": exc.used_bytes,
                "requested_bytes": exc.requested_bytes,
            },
        ) from exc
    except Exception:
        await storage.delete_file(record.storage_path)
        raise
    return record


@router.post(
    "/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file(
    file: Annotated[UploadFile, File(...)],
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.upload"))],
) -> FileResourceResponse | JSONResponse:
    result = await _persist_upload(file, ctx)
    return result if isinstance(result, JSONResponse) else _serialize(result)


@router.post(
    "/files/upload",
    response_model=FileUploadResponse,
    deprecated=True,
)
async def upload_file_compatibility(
    file: Annotated[UploadFile, File(...)],
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.upload"))],
) -> FileResourceResponse | JSONResponse:
    """Compatibility route retained while clients migrate to POST /api/files."""
    result = await _persist_upload(file, ctx)
    return result if isinstance(result, JSONResponse) else _serialize(result)


@router.get("/files", response_model=FileListResponse)
def list_files(
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> FileListResponse:
    records, total = get_file_store().list_scoped(
        _workspace_id(ctx),
        page=page,
        limit=limit,
        query=q,
    )
    return FileListResponse(
        items=[_serialize(record) for record in records],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/files/{file_id}", response_model=FileResourceResponse)
def get_file_metadata(
    file_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.view"))],
) -> FileResourceResponse:
    record = get_file_store().get_scoped(file_id, _workspace_id(ctx))
    if record is None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found")
    return _serialize(record)


@router.get(
    "/files/{file_id}/content",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": "The stored file content.",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def download_file(
    file_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.view"))],
) -> Response:
    record = get_file_store().get_scoped(file_id, _workspace_id(ctx))
    if record is None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found")
    try:
        content = await get_storage().read_file(record.storage_path)
    except FileNotFoundError as exc:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File content not found") from exc
    encoded_name = quote(record.filename, safe="")
    return Response(
        content=content,
        media_type=record.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "ETag": f'"sha256:{record.sha256}"',
        },
    )


@router.get(
    "/files/{file_id}/deletion-impact",
    response_model=FileDeletionImpactResponse,
)
def get_file_deletion_impact(
    file_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.delete"))],
) -> FileDeletionImpactResponse:
    impact = get_file_store().deletion_impact(file_id, _workspace_id(ctx))
    if impact is None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found")
    reason = "referenced_by_runs" if not impact.can_delete else None
    return FileDeletionImpactResponse(
        can_delete=impact.can_delete,
        file_id=file_id,
        run_references=impact.run_references,
        active_run_references=impact.active_run_references,
        reason=reason,
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("file.delete"))],
) -> Response:
    store = get_file_store()
    workspace_id = _workspace_id(ctx)
    retained = store.get_scoped(file_id, workspace_id, include_deleted=True)
    if retained is None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found")
    if retained.status == "deleted":
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if retained.status == "cleanup_failed":
        try:
            await get_storage().delete_file(retained.storage_path)
        except OSError as exc:
            raise AppError(
                ErrorCode.FILE_CLEANUP_FAILED,
                "File storage cleanup retry failed",
            ) from exc
        store.mark_cleanup_complete(file_id, workspace_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    impact = store.deletion_impact(file_id, workspace_id)
    assert impact is not None
    if not impact.can_delete:
        raise AppError(
            ErrorCode.FILE_IN_USE,
            "File is referenced by one or more runs",
            details={
                "run_references": impact.run_references,
                "active_run_references": impact.active_run_references,
            },
        )
    record = store.mark_deleted(file_id, workspace_id)
    if record is None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found")
    try:
        await get_storage().delete_file(record.storage_path)
    except OSError as exc:
        store.mark_cleanup_failed(file_id, "STORAGE_DELETE_FAILED")
        raise AppError(
            ErrorCode.FILE_CLEANUP_FAILED,
            "File metadata was deleted but storage cleanup failed",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
