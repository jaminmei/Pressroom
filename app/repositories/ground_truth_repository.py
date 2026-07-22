"""Repository for evaluation ground truth versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.ground_truth import GroundTruth
from app.models.db.test_document import TestDocument
from app.models.db.test_set import TestSet
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GroundTruthRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create_version(
        self,
        *,
        document_id: str,
        source: str,
        format: str,
        content: str,
        source_task_run_id: str | None = None,
        notes: str | None = None,
        workspace_id: str | None = None,
    ) -> GroundTruth:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = (
                select(func.max(GroundTruth.version))
                .select_from(GroundTruth)
                .join(TestDocument, TestDocument.id == GroundTruth.document_id)
                .join(TestSet, TestSet.id == TestDocument.test_set_id)
                .where(GroundTruth.document_id == document_id)
            )
            statement = statement.where(TestSet.workspace_id == workspace_id)
            latest_version = await session.scalar(statement)
            record = GroundTruth(
                id=f"gt_{uuid4()}",
                document_id=document_id,
                version=int(latest_version or 0) + 1,
                source=source,
                format=format,
                content=content,
                source_task_run_id=source_task_run_id,
                notes=notes,
                created_at=_utcnow_naive(),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_latest(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
    ) -> GroundTruth | None:
        _require_workspace_filter(workspace_id)
        statement = (
            select(GroundTruth)
            .join(TestDocument, TestDocument.id == GroundTruth.document_id)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(GroundTruth.document_id == document_id)
            .order_by(GroundTruth.version.desc())
            .limit(1)
        )
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            return cast(GroundTruth | None, await session.scalar(statement))

    async def get_version(
        self,
        document_id: str,
        version: int,
        *,
        workspace_id: str | None = None,
    ) -> GroundTruth | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(GroundTruth)
            .join(TestDocument, TestDocument.id == GroundTruth.document_id)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(GroundTruth.document_id == document_id)
            .where(GroundTruth.version == version)
            .where(TestSet.workspace_id == workspace_id)
        )
        async with self._session_factory() as session:
            return cast(GroundTruth | None, await session.scalar(statement))

    async def get_document_ids_with_ground_truth(
        self,
        document_ids: list[str],
        *,
        workspace_id: str | None = None,
    ) -> set[str]:
        """Return workspace-scoped document IDs that have at least one GT version."""
        workspace_id = _require_workspace_filter(workspace_id)
        if not document_ids:
            return set()

        statement = (
            select(GroundTruth.document_id)
            .distinct()
            .join(TestDocument, TestDocument.id == GroundTruth.document_id)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(GroundTruth.document_id.in_(document_ids))
            .where(TestSet.workspace_id == workspace_id)
        )
        async with self._session_factory() as session:
            rows = await session.scalars(statement)
            return set(rows.all())

    async def list_versions(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[GroundTruth]:
        _require_workspace_filter(workspace_id)
        statement = (
            select(GroundTruth)
            .join(TestDocument, TestDocument.id == GroundTruth.document_id)
            .join(TestSet, TestSet.id == TestDocument.test_set_id)
            .where(GroundTruth.document_id == document_id)
            .order_by(GroundTruth.version.desc())
        )
        statement = statement.where(TestSet.workspace_id == workspace_id)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())
