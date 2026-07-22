"""Repository for durable task event log access."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.task_event_log import TaskEventLog
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


class EventLogRepository:
    """Persist and query task event logs for SSE replay."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def append(
        self,
        task_run_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None,
    ) -> TaskEventLog:
        payload_data = dict(payload) if payload is not None else None
        event_log = TaskEventLog(
            task_run_id=task_run_id,
            event_type=event_type,
            payload=payload_data,
        )

        async with self._session_factory() as session:
            await self._ensure_task_run(session, task_run_id)
            session.add(event_log)
            await session.commit()
            await session.refresh(event_log)
            return event_log

    async def _ensure_task_run(self, session: AsyncSession, task_run_id: str) -> None:
        await session.execute(
            text(
                "INSERT INTO task_runs (id, source, created_at) "
                "VALUES (:task_id, :source, :created_at) "
                "ON CONFLICT(id) DO NOTHING"
            ),
            {"task_id": task_run_id, "source": "event_log", "created_at": datetime.utcnow()},
        )

    async def list_after(
        self,
        task_run_id: str,
        cursor_seq: int,
        *,
        limit: int | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskEventLog]:
        _require_workspace_filter(workspace_id)
        statement = (
            select(TaskEventLog)
            .where(
                TaskEventLog.task_run_id == task_run_id,
                TaskEventLog.seq > cursor_seq,
            )
            .order_by(TaskEventLog.seq.asc())
        )
        statement = statement.where(
            TaskEventLog.task_run_id.in_(
                text("SELECT id FROM task_runs WHERE workspace_id = :workspace_id")
            )
        )
        if limit is not None:
            statement = statement.limit(max(limit, 0))

        async with self._session_factory() as session:
            results = await session.scalars(statement, params={"workspace_id": workspace_id})
            return list(results.all())

    async def count(self, task_run_id: str, *, workspace_id: str | None = None) -> int:
        _require_workspace_filter(workspace_id)
        statement = select(func.count(TaskEventLog.seq)).where(
            TaskEventLog.task_run_id == task_run_id
        )
        statement = statement.where(
            TaskEventLog.task_run_id.in_(
                text("SELECT id FROM task_runs WHERE workspace_id = :workspace_id")
            )
        )

        async with self._session_factory() as session:
            total = await session.scalar(statement, params={"workspace_id": workspace_id})
            return int(total or 0)

    async def get_last_seq(self, task_run_id: str, *, workspace_id: str | None = None) -> int:
        _require_workspace_filter(workspace_id)
        statement = select(func.max(TaskEventLog.seq)).where(
            TaskEventLog.task_run_id == task_run_id
        )
        statement = statement.where(
            TaskEventLog.task_run_id.in_(
                text("SELECT id FROM task_runs WHERE workspace_id = :workspace_id")
            )
        )

        async with self._session_factory() as session:
            last_seq = await session.scalar(statement, params={"workspace_id": workspace_id})
            return int(last_seq or 0)

    async def task_exists(self, task_run_id: str, *, workspace_id: str | None = None) -> bool:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT 1 FROM task_runs WHERE id = :task_id"
                    " AND workspace_id = :workspace_id LIMIT 1"
                ),
                {"task_id": task_run_id, "workspace_id": workspace_id},
            )
            return result.scalar_one_or_none() is not None
