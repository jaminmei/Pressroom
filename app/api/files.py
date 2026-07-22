from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import require_workspace_capability
from app.api.task_helpers import validate_upload
from app.config import get_settings
from app.errors.error_response import CANONICAL_ERROR_RESPONSES
from app.services.file_store import FileStore, UploadedFileRecord
from app.services.workspace_access import ResolvedContext
from app.storage.local import get_storage

router = APIRouter(responses=CANONICAL_ERROR_RESPONSES)


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int


@lru_cache
def get_file_store() -> FileStore:
    return FileStore()


@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: Annotated[UploadFile, File(...)],
    ctx: Annotated[ResolvedContext, Depends(require_workspace_capability("workflow.run"))],
) -> JSONResponse:
    settings = get_settings()

    content = await validate_upload(file, settings)
    if isinstance(content, JSONResponse):
        return content

    mime_type = (file.content_type or "").lower()
    task_id = str(uuid4())
    file_id = f"file_{uuid4()}"
    raw_filename = (file.filename or "upload.bin").replace("\\", "/")
    filename = Path(raw_filename).name

    storage = get_storage()
    storage_path = await storage.save_file(task_id, "original", filename, content)

    get_file_store().put(
        UploadedFileRecord(
            file_id=file_id,
            storage_path=storage_path,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            workspace_id=ctx.workspace_id,
            uploaded_by_user_id=ctx.user.id,
            created_at=datetime.now(timezone.utc),
        )
    )

    return JSONResponse(
        status_code=200,
        content={
            "file_id": file_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(content),
        },
    )
