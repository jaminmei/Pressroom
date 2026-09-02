from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class FileResourceResponse(FileApiModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: Literal["active", "deleted", "cleanup_failed"]
    uploaded_by_user_id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class FileListResponse(FileApiModel):
    items: list[FileResourceResponse]
    total: int
    page: int
    limit: int


class FileDeletionImpactResponse(FileApiModel):
    can_delete: bool
    file_id: str
    run_references: int
    active_run_references: int
    reason: str | None


class FileUploadResponse(FileResourceResponse):
    pass


class FileListQuery(FileApiModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=200)
