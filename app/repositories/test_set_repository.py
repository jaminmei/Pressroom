"""Repository for evaluation test sets and documents."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.test_document import TestDocument
from app.models.db.test_set import TestSet
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    ) -> None:
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
            await session.delete(record)
            await session.flush()
            await self._refresh_document_count(session, test_set_id, workspace_id=workspace_id)
            await session.commit()

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

    async def delete_test_set(self, test_set_id: str, *, workspace_id: str | None = None) -> None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = select(TestSet).where(TestSet.id == test_set_id)
            statement = statement.where(TestSet.workspace_id == workspace_id)
            record = await session.scalar(statement)
            if record is None:
                raise KeyError(test_set_id)
            await session.delete(record)
            await session.commit()

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
