"""Repository for durable node run state lookups."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.db.session import AsyncSessionLocal
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


@dataclass(slots=True)
class NodeRunSnapshot:
    task_run_id: str
    node_id: str
    node_type: str | None = None
    status: str | None = None
    attempt: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None


_column_cache: dict[str, set[str]] = {}


class NodeRunRepository:
    """Load persisted node state from ``node_runs`` for queue-mode recovery flows."""

    _OPTIONAL_COLUMNS: tuple[str, ...] = (
        "task_run_id",
        "node_id",
        "node_type",
        "status",
        "attempt",
        "duration_ms",
        "error",
        "started_at",
        "completed_at",
        "updated_at",
    )

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def get_snapshot(
        self,
        task_id: str,
        node_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> NodeRunSnapshot | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            columns = await self._get_columns(session)
            if not columns:
                return None

            selected_columns = [name for name in self._OPTIONAL_COLUMNS if name in columns]
            if "task_run_id" not in selected_columns or "node_id" not in selected_columns:
                return None

            order_by = "updated_at DESC" if "updated_at" in columns else "node_id ASC"
            statement = text(
                "SELECT "
                f"{', '.join(selected_columns)} "
                "FROM node_runs "
                "WHERE task_run_id = :task_id AND node_id = :node_id "
                "AND task_run_id IN ("
                "SELECT id FROM task_runs WHERE workspace_id = :workspace_id"
                ")) "
                f"ORDER BY {order_by} LIMIT 1"
            )
            result = await session.execute(
                statement,
                {"task_id": task_id, "node_id": node_id, "workspace_id": workspace_id},
            )
            row = result.mappings().first()
            if row is None:
                return None

            if expected_workspace_id is not None:
                owning_workspace_id = await session.scalar(
                    text("SELECT workspace_id FROM task_runs WHERE id = :task_id LIMIT 1"),
                    {"task_id": task_id},
                )
                if owning_workspace_id != expected_workspace_id:
                    return None

            return self._row_to_snapshot(cast(Mapping[str, Any], row))

    async def _get_columns(self, session: AsyncSession) -> set[str]:
        if "node_runs" in _column_cache:
            return _column_cache["node_runs"]

        def _load_columns(sync_session: SyncSession) -> set[str]:
            bind = sync_session.get_bind()
            inspector = sa.inspect(bind)
            if not inspector.has_table("node_runs"):
                return set()
            return {str(column["name"]) for column in inspector.get_columns("node_runs")}

        columns = cast(set[str], await session.run_sync(_load_columns))
        _column_cache["node_runs"] = columns
        return columns

    def _row_to_snapshot(self, row: Mapping[str, Any]) -> NodeRunSnapshot:
        return NodeRunSnapshot(
            task_run_id=str(row.get("task_run_id", "")),
            node_id=str(row.get("node_id", "")),
            node_type=self._as_optional_str(row.get("node_type")),
            status=self._as_optional_str(row.get("status")),
            attempt=self._as_optional_int(row.get("attempt")),
            duration_ms=self._as_optional_int(row.get("duration_ms")),
            error=self._as_optional_str(row.get("error")),
            started_at=self._parse_datetime(row.get("started_at")),
            completed_at=self._parse_datetime(row.get("completed_at")),
            updated_at=self._parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _as_optional_str(value: object) -> str | None:
        if value is None:
            return None
        text_value = str(value)
        return text_value if text_value else None

    @staticmethod
    def _as_optional_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
                return int(stripped)
        return None

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if not isinstance(value, str):
            return None

        text_value = value.strip()
        if not text_value:
            return None

        normalized = text_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
