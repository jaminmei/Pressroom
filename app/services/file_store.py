from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class UploadedFileRecord:
    file_id: str
    storage_path: str
    filename: str
    mime_type: str
    size_bytes: int
    workspace_id: str | None = None
    uploaded_by_user_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FileStore:
    """In-memory file id -> storage metadata mapping for workflow execution."""

    def __init__(self) -> None:
        self._files: dict[str, UploadedFileRecord] = {}

    def put(self, record: UploadedFileRecord) -> None:
        self._files[record.file_id] = record

    def get(self, file_id: str) -> UploadedFileRecord | None:
        return self._files.get(file_id)

    def get_owned(
        self, file_id: str, workspace_id: str, uploaded_by_user_id: str
    ) -> UploadedFileRecord | None:
        record = self.get(file_id)
        if record is None:
            return None
        if record.workspace_id != workspace_id or record.uploaded_by_user_id != uploaded_by_user_id:
            return None
        return record

    def clear(self) -> None:
        self._files.clear()
