from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.db.file_resource import FileResource
from app.models.db.task_run import TaskRun
from app.models.db.task_run_file import TaskRunFile
from app.models.db.workspace import Workspace

SessionFactory = Callable[[], Session]
TERMINAL_RUN_STATUSES = {"completed", "partial_completed", "failed", "cancelled"}


@dataclass(frozen=True, slots=True)
class UploadedFileRecord:
    file_id: str
    storage_path: str
    filename: str
    mime_type: str
    size_bytes: int
    workspace_id: str | None = None
    uploaded_by_user_id: str | None = None
    sha256: str = ""
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FileDeletionImpact:
    file_id: str
    run_references: int
    active_run_references: int

    @property
    def can_delete(self) -> bool:
        return self.run_references == 0


@dataclass(frozen=True, slots=True)
class FileQuotaExceededError(Exception):
    quota_bytes: int
    used_bytes: int
    requested_bytes: int


def _utc_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FileStore:
    """Database-backed workspace file metadata facade used by APIs and execution."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or SessionLocal

    def put(self, record: UploadedFileRecord) -> None:
        if not record.workspace_id or not record.uploaded_by_user_id:
            raise ValueError("workspace_id and uploaded_by_user_id are required")
        with self._session_factory() as session:
            self._apply_record(session, record)
            session.commit()

    def put_with_quota(self, record: UploadedFileRecord, *, quota_bytes: int) -> None:
        if not record.workspace_id or not record.uploaded_by_user_id:
            raise ValueError("workspace_id and uploaded_by_user_id are required")
        with self._session_factory() as session, session.begin():
            workspace = session.scalar(
                select(Workspace).where(Workspace.id == record.workspace_id).with_for_update()
            )
            if workspace is None or workspace.status != "active":
                raise ValueError("workspace is unavailable")
            used_bytes = int(
                session.scalar(
                    select(func.coalesce(func.sum(FileResource.size_bytes), 0)).where(
                        FileResource.workspace_id == record.workspace_id,
                        FileResource.status == "active",
                    )
                )
                or 0
            )
            if used_bytes + record.size_bytes > quota_bytes:
                raise FileQuotaExceededError(
                    quota_bytes=quota_bytes,
                    used_bytes=used_bytes,
                    requested_bytes=record.size_bytes,
                )
            self._apply_record(session, record)

    def get(self, file_id: str) -> UploadedFileRecord | None:
        with self._session_factory() as session:
            row = session.get(FileResource, file_id)
            return self._record(row) if row is not None else None

    def get_scoped(
        self,
        file_id: str,
        workspace_id: str,
        *,
        include_deleted: bool = False,
    ) -> UploadedFileRecord | None:
        with self._session_factory() as session:
            statement = select(FileResource).where(
                FileResource.id == file_id,
                FileResource.workspace_id == workspace_id,
            )
            if not include_deleted:
                statement = statement.where(FileResource.status == "active")
            row = session.scalar(statement)
            return self._record(row) if row is not None else None

    def get_owned(
        self,
        file_id: str,
        workspace_id: str,
        uploaded_by_user_id: str,
    ) -> UploadedFileRecord | None:
        """Compatibility method; files are shared inside a workspace, not uploader-only."""
        del uploaded_by_user_id
        return self.get_scoped(file_id, workspace_id)

    def list_scoped(
        self,
        workspace_id: str,
        *,
        page: int = 1,
        limit: int = 50,
        query: str | None = None,
    ) -> tuple[list[UploadedFileRecord], int]:
        filters = [
            FileResource.workspace_id == workspace_id,
            FileResource.status == "active",
        ]
        if query:
            filters.append(FileResource.filename.ilike(f"%{query.strip()}%"))
        with self._session_factory() as session:
            total = int(session.scalar(select(func.count(FileResource.id)).where(*filters)) or 0)
            rows = session.scalars(
                select(FileResource)
                .where(*filters)
                .order_by(FileResource.created_at.desc(), FileResource.id.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            ).all()
            return [self._record(row) for row in rows], total

    def deletion_impact(self, file_id: str, workspace_id: str) -> FileDeletionImpact | None:
        record = self.get_scoped(file_id, workspace_id, include_deleted=True)
        if record is None or record.status == "deleted":
            return None
        if record.status == "cleanup_failed":
            return FileDeletionImpact(
                file_id=file_id,
                run_references=0,
                active_run_references=0,
            )
        with self._session_factory() as session:
            associated = set(
                session.scalars(
                    select(TaskRunFile.task_run_id).where(
                        TaskRunFile.workspace_id == workspace_id,
                        TaskRunFile.file_id == file_id,
                    )
                )
            )
            rows = session.execute(
                select(TaskRun.id, TaskRun.status, TaskRun.input_files_json).where(
                    TaskRun.workspace_id == workspace_id
                )
            ).all()
            statuses: dict[str, str | None] = {}
            for task_id, status, bindings_json in rows:
                task_id = str(task_id)
                if task_id in associated or self._json_references_file(bindings_json, file_id):
                    associated.add(task_id)
                    statuses[task_id] = str(status) if status is not None else None
            total = len(associated)
            active = sum(
                statuses.get(task_id) not in TERMINAL_RUN_STATUSES for task_id in associated
            )
        return FileDeletionImpact(
            file_id=file_id,
            run_references=total,
            active_run_references=active,
        )

    def active_usage_bytes(self, workspace_id: str) -> int:
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.coalesce(func.sum(FileResource.size_bytes), 0)).where(
                        FileResource.workspace_id == workspace_id,
                        FileResource.status == "active",
                    )
                )
                or 0
            )

    def purge_expired_deleted_metadata(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
    ) -> int:
        threshold = _utc_naive(now) - timedelta(days=retention_days)
        with self._session_factory() as session:
            expired_ids = list(
                session.scalars(
                    select(FileResource.id).where(
                        FileResource.status == "deleted",
                        FileResource.deleted_at.is_not(None),
                        FileResource.deleted_at <= threshold,
                    )
                )
            )
            if expired_ids:
                session.execute(delete(FileResource).where(FileResource.id.in_(expired_ids)))
            session.commit()
            return len(expired_ids)

    def mark_deleted(self, file_id: str, workspace_id: str) -> UploadedFileRecord | None:
        now = _utc_naive()
        with self._session_factory() as session:
            row = session.scalar(
                select(FileResource).where(
                    FileResource.id == file_id,
                    FileResource.workspace_id == workspace_id,
                    FileResource.status == "active",
                )
            )
            if row is None:
                return None
            row.status = "deleted"
            row.deleted_at = now
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._record(row)

    def mark_cleanup_failed(self, file_id: str, error_code: str) -> None:
        with self._session_factory() as session:
            row = session.get(FileResource, file_id)
            if row is None:
                return
            row.status = "cleanup_failed"
            row.cleanup_error_code = error_code
            row.updated_at = _utc_naive()
            session.add(row)
            session.commit()

    def mark_cleanup_complete(self, file_id: str, workspace_id: str) -> None:
        with self._session_factory() as session:
            row = session.scalar(
                select(FileResource).where(
                    FileResource.id == file_id,
                    FileResource.workspace_id == workspace_id,
                    FileResource.status == "cleanup_failed",
                )
            )
            if row is None:
                return
            row.status = "deleted"
            row.cleanup_error_code = None
            row.updated_at = _utc_naive()
            session.add(row)
            session.commit()

    def clear(self) -> None:
        with self._session_factory() as session:
            session.execute(delete(FileResource))
            session.commit()

    @staticmethod
    def _json_references_file(value: str | None, file_id: str) -> bool:
        if not value:
            return False
        try:
            items = json.loads(value)
        except json.JSONDecodeError:
            return False
        return isinstance(items, list) and any(
            isinstance(item, dict) and item.get("file_id") == file_id for item in items
        )

    @staticmethod
    def _record(row: FileResource) -> UploadedFileRecord:
        return UploadedFileRecord(
            file_id=row.id,
            storage_path=row.storage_key,
            filename=row.filename,
            mime_type=row.mime_type,
            size_bytes=row.size_bytes,
            workspace_id=row.workspace_id,
            uploaded_by_user_id=row.uploaded_by_user_id,
            sha256=row.sha256,
            status=row.status,
            created_at=_utc_aware(row.created_at) or datetime.now(timezone.utc),
            updated_at=_utc_aware(row.updated_at) or datetime.now(timezone.utc),
            deleted_at=_utc_aware(row.deleted_at),
        )

    @staticmethod
    def _apply_record(session: Session, record: UploadedFileRecord) -> None:
        now = _utc_naive(record.updated_at)
        row = session.get(FileResource, record.file_id)
        if row is None:
            row = FileResource(
                id=record.file_id,
                workspace_id=str(record.workspace_id),
                uploaded_by_user_id=str(record.uploaded_by_user_id),
                storage_key=record.storage_path,
                filename=record.filename,
                mime_type=record.mime_type,
                size_bytes=record.size_bytes,
                sha256=record.sha256,
                status=record.status,
                created_at=_utc_naive(record.created_at),
                updated_at=now,
                deleted_at=_utc_naive(record.deleted_at) if record.deleted_at else None,
            )
        else:
            row.storage_key = record.storage_path
            row.filename = record.filename
            row.mime_type = record.mime_type
            row.size_bytes = record.size_bytes
            row.sha256 = record.sha256
            row.status = record.status
            row.updated_at = now
            row.deleted_at = _utc_naive(record.deleted_at) if record.deleted_at else None
        session.add(row)
