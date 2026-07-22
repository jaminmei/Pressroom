"""Transactional repository for evaluation dispatch outbox rows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.evaluation_dispatch_outbox import (
    DISPATCH_CANCELLED,
    DISPATCH_PENDING,
    DISPATCH_PUBLISHED,
    DISPATCH_PUBLISHING,
    EvaluationDispatchOutbox,
)
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun

SessionFactory = Callable[[], AsyncSession]
DEFAULT_PUBLISH_RETRY_DELAY_SECONDS = 5
MAX_PUBLISH_RETRY_DELAY_SECONDS = 60


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EvaluationDispatchRepository:
    """Own outbox state transitions and their transaction boundaries."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create_pending(
        self,
        *,
        evaluation_result_id: str,
        task_run_id: str,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> EvaluationDispatchOutbox:
        now = created_at or _utcnow_naive()
        record = EvaluationDispatchOutbox(
            id=f"eval_dispatch_{uuid4()}",
            evaluation_result_id=evaluation_result_id,
            task_run_id=task_run_id,
            status=DISPATCH_PENDING,
            attempt_count=0,
            available_at=available_at or now,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            async with session.begin():
                session.add(record)
                await session.flush()
            await session.refresh(record)
            return record

    async def get_for_result(
        self,
        evaluation_result_id: str,
    ) -> EvaluationDispatchOutbox | None:
        statement = select(EvaluationDispatchOutbox).where(
            EvaluationDispatchOutbox.evaluation_result_id == evaluation_result_id
        )
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            return record

    async def list_for_run(self, evaluation_run_id: str) -> list[EvaluationDispatchOutbox]:
        statement = (
            select(EvaluationDispatchOutbox)
            .join(
                EvaluationResult,
                EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
            )
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationDispatchOutbox.created_at.asc(), EvaluationDispatchOutbox.id.asc())
        )
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def claim_pending(
        self,
        *,
        limit: int = 100,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> list[EvaluationDispatchOutbox]:
        if limit <= 0:
            return []
        claimed_at = now or _utcnow_naive()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        async with self._session_factory() as session:
            async with session.begin():
                await self._recover_expired_leases(session, claimed_at)
                statement = (
                    select(EvaluationDispatchOutbox)
                    .join(
                        EvaluationResult,
                        EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
                    )
                    .join(
                        EvaluationRun,
                        EvaluationRun.id == EvaluationResult.evaluation_run_id,
                    )
                    .where(
                        EvaluationDispatchOutbox.status == DISPATCH_PENDING,
                        EvaluationDispatchOutbox.available_at <= claimed_at,
                        EvaluationRun.status.in_(("pending", "running")),
                    )
                    .order_by(
                        EvaluationDispatchOutbox.available_at.asc(),
                        EvaluationDispatchOutbox.created_at.asc(),
                        EvaluationDispatchOutbox.id.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                result = await session.scalars(statement)
                rows = list(result.all())
                for row in rows:
                    row.status = DISPATCH_PUBLISHING
                    row.attempt_count += 1
                    row.lease_expires_at = lease_expires_at
                    row.updated_at = claimed_at
                await session.flush()
            return rows

    @asynccontextmanager
    async def publish_guard(self, outbox_id: str) -> AsyncIterator[bool]:
        """Serialize broker publication with run cancellation.

        PostgreSQL uses the same session advisory lock as
        ``EvaluationRepository.cancel_run``. After acquiring it, the guard
        re-checks both the outbox and run states so a row cancelled after it
        was claimed is never sent. The lock remains held across the broker
        send and ``mark_published`` call made by the publisher.
        """
        session = self._session_factory()
        locked_run_id: str | None = None
        try:
            run_id = await session.scalar(
                select(EvaluationResult.evaluation_run_id)
                .join(
                    EvaluationDispatchOutbox,
                    EvaluationDispatchOutbox.evaluation_result_id == EvaluationResult.id,
                )
                .where(EvaluationDispatchOutbox.id == outbox_id)
            )
            if run_id is None:
                yield False
                return

            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_lock(hashtext(:rid))"),
                    {"rid": run_id},
                )
                await session.commit()
                locked_run_id = run_id

            eligible = await session.scalar(
                select(func.count(EvaluationDispatchOutbox.id))
                .join(
                    EvaluationResult,
                    EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
                )
                .join(
                    EvaluationRun,
                    EvaluationRun.id == EvaluationResult.evaluation_run_id,
                )
                .where(
                    EvaluationDispatchOutbox.id == outbox_id,
                    EvaluationDispatchOutbox.status == DISPATCH_PUBLISHING,
                    EvaluationRun.status.in_(("pending", "running")),
                )
            )
            await session.commit()
            yield bool(eligible)
        finally:
            if locked_run_id is not None:
                try:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:rid))"),
                        {"rid": locked_run_id},
                    )
                    await session.commit()
                finally:
                    await session.close()
            else:
                await session.close()

    async def mark_published(
        self,
        outbox_id: str,
        *,
        published_at: datetime | None = None,
    ) -> EvaluationDispatchOutbox | None:
        completed_at = published_at or _utcnow_naive()
        async with self._session_factory() as session:
            async with session.begin():
                statement = select(EvaluationDispatchOutbox).where(
                    EvaluationDispatchOutbox.id == outbox_id,
                    EvaluationDispatchOutbox.status == DISPATCH_PUBLISHING,
                )
                record = await session.scalar(statement)
                if record is None:
                    return None
                record.status = DISPATCH_PUBLISHED
                record.published_at = completed_at
                record.lease_expires_at = None
                record.last_error = None
                record.updated_at = completed_at
                await session.flush()
            await session.refresh(record)
            return record

    async def mark_publish_failed(
        self,
        outbox_id: str,
        *,
        error: str,
        retry_delay_seconds: int | None = None,
        failed_at: datetime | None = None,
    ) -> EvaluationDispatchOutbox | None:
        failed_at = failed_at or _utcnow_naive()
        async with self._session_factory() as session:
            async with session.begin():
                statement = select(EvaluationDispatchOutbox).where(
                    EvaluationDispatchOutbox.id == outbox_id,
                    EvaluationDispatchOutbox.status == DISPATCH_PUBLISHING,
                )
                record = await session.scalar(statement)
                if record is None:
                    return None
                if retry_delay_seconds is None:
                    retry_delay_seconds = min(
                        DEFAULT_PUBLISH_RETRY_DELAY_SECONDS
                        * (2 ** max(record.attempt_count - 1, 0)),
                        MAX_PUBLISH_RETRY_DELAY_SECONDS,
                    )
                available_at = failed_at + timedelta(seconds=max(0, retry_delay_seconds))
                record.status = DISPATCH_PENDING
                record.available_at = available_at
                record.lease_expires_at = None
                record.last_error = error
                record.updated_at = failed_at
                await session.flush()
            await session.refresh(record)
            return record

    async def recover_expired_leases(self, *, now: datetime | None = None) -> int:
        recovered_at = now or _utcnow_naive()
        async with self._session_factory() as session:
            async with session.begin():
                count = await self._recover_expired_leases(session, recovered_at)
            return count

    async def cancel_for_run(
        self,
        evaluation_run_id: str,
        *,
        cancelled_at: datetime | None = None,
    ) -> int:
        cancelled_at = cancelled_at or _utcnow_naive()
        async with self._session_factory() as session:
            async with session.begin():
                statement = (
                    select(EvaluationDispatchOutbox)
                    .join(
                        EvaluationResult,
                        EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
                    )
                    .where(
                        EvaluationResult.evaluation_run_id == evaluation_run_id,
                        EvaluationDispatchOutbox.status.in_(
                            (DISPATCH_PENDING, DISPATCH_PUBLISHING)
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
                result = await session.scalars(statement)
                rows = list(result.all())
                for row in rows:
                    row.status = DISPATCH_CANCELLED
                    row.lease_expires_at = None
                    row.updated_at = cancelled_at
                await session.flush()
                return len(rows)

    async def has_eligible_work(self, *, now: datetime | None = None) -> bool:
        checked_at = now or _utcnow_naive()
        statement = select(func.count(EvaluationDispatchOutbox.id)).where(
            EvaluationDispatchOutbox.status == DISPATCH_PENDING,
            EvaluationDispatchOutbox.available_at <= checked_at,
        )
        async with self._session_factory() as session:
            count = await session.scalar(statement)
            return bool(count)

    async def next_available_at(self) -> datetime | None:
        statement = (
            select(EvaluationDispatchOutbox.available_at)
            .where(EvaluationDispatchOutbox.status == DISPATCH_PENDING)
            .order_by(EvaluationDispatchOutbox.available_at.asc())
            .limit(1)
        )
        async with self._session_factory() as session:
            value = await session.scalar(statement)
            return value

    async def _recover_expired_leases(
        self,
        session: AsyncSession,
        now: datetime,
    ) -> int:
        statement = (
            update(EvaluationDispatchOutbox)
            .where(
                EvaluationDispatchOutbox.status == DISPATCH_PUBLISHING,
                EvaluationDispatchOutbox.lease_expires_at.is_not(None),
                EvaluationDispatchOutbox.lease_expires_at <= now,
            )
            .values(
                status=DISPATCH_PENDING,
                available_at=now,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        result = await session.execute(statement)
        rowcount = getattr(result, "rowcount", 0) or 0
        return int(rowcount)
