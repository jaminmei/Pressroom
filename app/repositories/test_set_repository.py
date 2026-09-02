"""Repository for evaluation test sets and documents."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.ground_truth import GroundTruth
from app.models.db.storage_cleanup_job import StorageCleanupJob
from app.models.db.test_document import TestDocument
from app.models.db.test_set import TestSet
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class TestSetDeletionImpact:
    test_set_id: str
    documents: int
    ground_truth_versions: int
    evaluation_runs: int
    active_evaluation_runs: int
    evaluation_results: int

    @property
    def can_delete(self) -> bool:
        return self.active_evaluation_runs == 0


@dataclass(frozen=True, slots=True)
class DocumentDeletionImpact:
    document_id: str
    ground_truth_versions: int
    evaluation_results: int
    active_evaluation_runs: int

    @property
    def can_delete(self) -> bool:
        return self.active_evaluation_runs == 0


class TestSetRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create_test_set(
        self,
        *,
        name: str,
        description: str | None,
        workspace_id: str | None = None,
    ) -> TestSet:
        now = _utcnow_naive()
        record = TestSet(
            id=f"ts_{uuid4()}",
            name=name,
            description=description,
            workspace_id=workspace_id,
            document_count=0,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def list_test_sets(self, *, workspace_id: str | None = None) -> list[TestSet]:
        _require_workspace_filter(workspace_id)
        statement = select(TestSet).order_by(TestSet.created_at.desc(), TestSet.id.desc())
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def get_test_set(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> TestSet | None:
        _require_workspace_filter(workspace_id)
        statement = select(TestSet).where(TestSet.id == test_set_id)
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            if record is None:
                return None
            if expected_workspace_id is not None and record.workspace_id != expected_workspace_id:
                return None
            return record

    async def create_test_document(
        self,
        *,
        test_set_id: str,
        filename: str,
        mime_type: str,
        storage_path: str,
        size_bytes: int | None,
        page_count: int | None,
        document_id: str | None = None,
    ) -> TestDocument:
        record = TestDocument(
            id=document_id or f"doc_{uuid4()}",
            test_set_id=test_set_id,
            filename=filename,
            mime_type=mime_type,
            storage_path=storage_path,
            size_bytes=size_bytes,
            page_count=page_count,
            created_at=_utcnow_naive(),
        )
        async with self._session_factory() as session:
            session.add(record)
            await session.flush()
            await self._refresh_document_count(session, test_set_id)
            await session.commit()
            await session.refresh(record)
            return record

    async def list_test_documents(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[TestDocument]:
        _require_workspace_filter(workspace_id)
        statement = (
            select(TestDocument)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(TestDocument.test_set_id == test_set_id)
            .order_by(TestDocument.created_at.desc(), TestDocument.id.desc())
        )
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def get_test_document(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> TestDocument | None:
        _require_workspace_filter(workspace_id)
        statement = (
            select(TestDocument)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(TestDocument.id == document_id)
        )
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            if record is None:
                return None
            if expected_workspace_id is None:
                return record
            owning_workspace_id = await session.scalar(
                select(TestSet.workspace_id).where(TestSet.id == record.test_set_id)
            )
            if owning_workspace_id != expected_workspace_id:
                return None
            return record

    async def delete_test_document(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
    ) -> str:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = (
                select(TestDocument)
                .join(TestSet, TestSet.id == TestDocument.test_set_id)
                .where(TestDocument.id == document_id)
            )
            statement = statement.where(TestSet.workspace_id == workspace_id)
            record = await session.scalar(statement)
            if record is None:
                raise KeyError(document_id)
            test_set_id = record.test_set_id
            cleanup_job_id = f"scj_{uuid4()}"
            now = _utcnow_naive()
            session.add(
                StorageCleanupJob(
                    id=cleanup_job_id,
                    workspace_id=str(workspace_id),
                    resource_type="test_document",
                    resource_id=document_id,
                    payload_json=json.dumps(
                        {
                            "test_set_id": test_set_id,
                            "document_id": document_id,
                            "storage_path": record.storage_path,
                        },
                        separators=(",", ":"),
                    ),
                    status="pending",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.delete(record)
            await session.flush()
            await self._refresh_document_count(session, test_set_id, workspace_id=workspace_id)
            await session.commit()
            return cleanup_job_id

    async def update_test_set(
        self,
        test_set_id: str,
        *,
        updates: dict[str, object],
        workspace_id: str | None = None,
    ) -> TestSet | None:
        """Update test set fields. Only keys present in `updates` are modified."""
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = select(TestSet).where(TestSet.id == test_set_id)
            statement = statement.where(TestSet.workspace_id == workspace_id)
            record = await session.scalar(statement)
            if record is None:
                return None
            for key, value in updates.items():
                setattr(record, key, value)
            record.updated_at = _utcnow_naive()
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def delete_test_set(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> str:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = select(TestSet).where(TestSet.id == test_set_id)
            statement = statement.where(TestSet.workspace_id == workspace_id)
            record = await session.scalar(statement)
            if record is None:
                raise KeyError(test_set_id)
            cleanup_job_id = f"scj_{uuid4()}"
            now = _utcnow_naive()
            session.add(
                StorageCleanupJob(
                    id=cleanup_job_id,
                    workspace_id=str(workspace_id),
                    resource_type="test_set",
                    resource_id=test_set_id,
                    payload_json=json.dumps(
                        {"test_set_id": test_set_id},
                        separators=(",", ":"),
                    ),
                    status="pending",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.delete(record)
            await session.commit()
            return cleanup_job_id

    async def mark_storage_cleanup_completed(self, cleanup_job_id: str) -> None:
        async with self._session_factory() as session:
            record = await session.get(StorageCleanupJob, cleanup_job_id)
            if record is None:
                return
            now = _utcnow_naive()
            record.status = "completed"
            record.attempts += 1
            record.error_code = None
            record.updated_at = now
            record.completed_at = now
            session.add(record)
            await session.commit()

    async def get_storage_cleanup_job(
        self,
        cleanup_job_id: str,
    ) -> StorageCleanupJob | None:
        async with self._session_factory() as session:
            return await session.get(StorageCleanupJob, cleanup_job_id)

    async def list_pending_storage_cleanup_job_ids(self, *, limit: int = 100) -> list[str]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(StorageCleanupJob.id)
                    .where(StorageCleanupJob.status.in_({"pending", "failed"}))
                    .order_by(StorageCleanupJob.created_at, StorageCleanupJob.id)
                    .limit(limit)
                )
            )

    async def mark_storage_cleanup_failed(
        self,
        cleanup_job_id: str,
        *,
        error_code: str,
    ) -> None:
        async with self._session_factory() as session:
            record = await session.get(StorageCleanupJob, cleanup_job_id)
            if record is None:
                return
            record.status = "failed"
            record.attempts += 1
            record.error_code = error_code
            record.updated_at = _utcnow_naive()
            session.add(record)
            await session.commit()

    async def get_test_set_deletion_impact(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> TestSetDeletionImpact | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            record = await session.scalar(
                select(TestSet).where(
                    TestSet.id == test_set_id,
                    TestSet.workspace_id == workspace_id,
                )
            )
            if record is None:
                return None
            documents = await session.scalar(
                select(func.count(TestDocument.id)).where(TestDocument.test_set_id == test_set_id)
            )
            ground_truth_versions = await session.scalar(
                select(func.count(GroundTruth.id))
                .join(TestDocument, TestDocument.id == GroundTruth.document_id)
                .where(TestDocument.test_set_id == test_set_id)
            )
            evaluation_runs = await session.scalar(
                select(func.count(EvaluationRun.id)).where(
                    EvaluationRun.test_set_id == test_set_id,
                    EvaluationRun.workspace_id == workspace_id,
                )
            )
            active_evaluation_runs = await session.scalar(
                select(func.count(EvaluationRun.id)).where(
                    EvaluationRun.test_set_id == test_set_id,
                    EvaluationRun.workspace_id == workspace_id,
                    EvaluationRun.status.in_(("pending", "queued", "running")),
                )
            )
            evaluation_results = await session.scalar(
                select(func.count(EvaluationResult.id))
                .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
                .where(
                    EvaluationRun.test_set_id == test_set_id,
                    EvaluationRun.workspace_id == workspace_id,
                )
            )
            return TestSetDeletionImpact(
                test_set_id=test_set_id,
                documents=int(documents or 0),
                ground_truth_versions=int(ground_truth_versions or 0),
                evaluation_runs=int(evaluation_runs or 0),
                active_evaluation_runs=int(active_evaluation_runs or 0),
                evaluation_results=int(evaluation_results or 0),
            )

    async def get_document_deletion_impact(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
    ) -> DocumentDeletionImpact | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            document = await session.scalar(
                select(TestDocument)
                .join(TestSet, TestSet.id == TestDocument.test_set_id)
                .where(
                    TestDocument.id == document_id,
                    TestSet.workspace_id == workspace_id,
                )
            )
            if document is None:
                return None
            ground_truth_versions = await session.scalar(
                select(func.count(GroundTruth.id)).where(GroundTruth.document_id == document_id)
            )
            evaluation_results = await session.scalar(
                select(func.count(EvaluationResult.id)).where(
                    EvaluationResult.document_id == document_id
                )
            )
            active_evaluation_runs = await session.scalar(
                select(func.count(EvaluationRun.id))
                .join(
                    EvaluationResult,
                    EvaluationResult.evaluation_run_id == EvaluationRun.id,
                )
                .where(
                    EvaluationResult.document_id == document_id,
                    EvaluationRun.workspace_id == workspace_id,
                    EvaluationRun.status.in_(("pending", "queued", "running")),
                )
            )
            return DocumentDeletionImpact(
                document_id=document_id,
                ground_truth_versions=int(ground_truth_versions or 0),
                evaluation_results=int(evaluation_results or 0),
                active_evaluation_runs=int(active_evaluation_runs or 0),
            )

    async def _refresh_document_count(
        self,
        session: AsyncSession,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> None:
        total = await session.scalar(
            select(func.count(TestDocument.id)).where(TestDocument.test_set_id == test_set_id)
        )
        statement = select(TestSet).where(TestSet.id == test_set_id)
        if workspace_id is not None:
            statement = statement.where(TestSet.workspace_id == workspace_id)
        record = await session.scalar(statement)
        if record is None:
            raise KeyError(test_set_id)
        record.document_count = int(total or 0)
        record.updated_at = _utcnow_naive()
        session.add(record)
