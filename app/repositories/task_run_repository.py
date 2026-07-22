"""Repository for durable task run snapshots and history queries."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.db.session import AsyncSessionLocal
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


@dataclass(slots=True)
class TaskRunSnapshot:
    task_id: str
    status: str | None = None
    workflow_id: str | None = None
    workflow_name: str | None = None
    run_name: str | None = None
    source: str | None = None
    workspace_id: str | None = None
    evaluation_run_id: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    node_summary: dict[str, int] | None = None
    result_preview: str | None = None
    results: list[dict[str, Any]] | None = None
    error: str | None = None
    dag_hash: str | None = None
    input_files: list[dict[str, Any]] | None = None
    workflow: dict[str, Any] | None = None
    updated_at: datetime | None = None


_column_cache: dict[str, set[str]] = {}


class TaskRunRepository:
    """Persist and query task run snapshots stored in task_runs."""

    _OPTIONAL_COLUMNS: tuple[str, ...] = (
        "status",
        "workflow_id",
        "workflow_name",
        "run_name",
        "source",
        "workspace_id",
        "evaluation_run_id",
        "created_at",
        "completed_at",
        "duration_ms",
        "node_summary_json",
        "result_preview",
        "results_json",
        "error",
        "dag_hash",
        "input_files_json",
        "workflow_json",
        "updated_at",
    )

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def upsert_snapshot(
        self,
        *,
        task_id: str,
        status: str,
        workflow_id: str | None,
        workflow_name: str | None,
        run_name: str | None = None,
        source: str | None = None,
        workspace_id: str | None = None,
        evaluation_run_id: str | None = None,
        created_at: datetime | None,
        completed_at: datetime | None,
        duration_ms: int | None,
        node_summary: Mapping[str, int] | None,
        result_preview: str | None,
        results: Sequence[Mapping[str, Any]] | None,
        error: str | None,
        dag_hash: str | None = None,
        input_files: Sequence[Mapping[str, Any]] | None = None,
        workflow: Mapping[str, Any] | None = None,
        updated_at: datetime | None,
    ) -> None:
        async with self._session_factory() as session:
            columns = await self._get_columns(session)
            if "id" not in columns:
                raise RuntimeError("task_runs table is missing required id column")

            await self._ensure_task_row(session, task_id)

            values: dict[str, object] = {
                "status": status,
                "source": source,
                "workspace_id": workspace_id,
                "evaluation_run_id": evaluation_run_id,
                "created_at": created_at,
                "completed_at": completed_at,
                "duration_ms": duration_ms,
                "node_summary_json": self._to_json(node_summary),
                "result_preview": result_preview,
                "results_json": self._to_json(list(results) if results is not None else None),
                "error": error,
                "updated_at": updated_at,
            }

            # Only update dag_hash / input_files / workflow when explicitly provided
            # (don't overwrite stored values with None on status-only updates)
            if dag_hash is not None:
                values["dag_hash"] = dag_hash
            if input_files is not None:
                values["input_files_json"] = self._to_json(list(input_files))
            if workflow is not None:
                values["workflow_json"] = self._to_json(dict(workflow))
            if run_name is not None:
                values["run_name"] = run_name
            if workflow_name is not None:
                values["workflow_name"] = workflow_name
            if workflow_id is not None:
                values["workflow_id"] = workflow_id

            update_values = {name: value for name, value in values.items() if name in columns}
            if update_values:
                await self._update_task_row(session, task_id, update_values)

            await session.commit()

    async def get_snapshot(
        self,
        task_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> TaskRunSnapshot | None:
        _require_workspace_filter(workspace_id)
        return await self._get_snapshot_unchecked(task_id, workspace_id, expected_workspace_id)

    async def get_snapshot_unchecked(
        self,
        task_id: str,
    ) -> TaskRunSnapshot | None:
        return await self._get_snapshot_unchecked(
            task_id, workspace_id=None, expected_workspace_id=None
        )

    async def _get_snapshot_unchecked(
        self,
        task_id: str,
        workspace_id: str | None,
        expected_workspace_id: str | None,
    ) -> TaskRunSnapshot | None:
        async with self._session_factory() as session:
            columns = await self._get_columns(session)
            if "id" not in columns:
                return None

            selected_columns = ["id", *[name for name in self._OPTIONAL_COLUMNS if name in columns]]
            if workspace_id is not None:
                statement = text(
                    f"SELECT {', '.join(selected_columns)} FROM task_runs WHERE id = :task_id"
                    " AND workspace_id = :workspace_id"
                )
                result = await session.execute(
                    statement,
                    {"task_id": task_id, "workspace_id": workspace_id},
                )
            else:
                statement = text(
                    f"SELECT {', '.join(selected_columns)} FROM task_runs WHERE id = :task_id"
                )
                result = await session.execute(statement, {"task_id": task_id})
            row = result.mappings().first()
            if row is None:
                return None

            if (
                expected_workspace_id is not None
                and row.get("workspace_id") != expected_workspace_id
            ):
                return None

            return self._row_to_snapshot(cast(Mapping[str, Any], row))

    async def list_snapshots(
        self,
        *,
        status: str = "all",
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRunSnapshot]:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            columns = await self._get_columns(session)
            if "id" not in columns:
                return []

            if status != "all" and "status" not in columns:
                return []
            if workflow_id and "workflow_id" not in columns:
                return []

            selected_columns = ["id", *[name for name in self._OPTIONAL_COLUMNS if name in columns]]
            where_clauses: list[str] = []
            params: dict[str, object] = {}

            if status != "all":
                where_clauses.append("status = :status")
                params["status"] = status

            if workflow_id:
                where_clauses.append("workflow_id = :workflow_id")
                params["workflow_id"] = workflow_id
            where_clauses.append("workspace_id = :workspace_id")
            params["workspace_id"] = workspace_id

            where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            order_by = "created_at DESC, id DESC" if "created_at" in columns else "id DESC"

            statement = text(
                f"SELECT {', '.join(selected_columns)} FROM task_runs"
                f"{where_sql} ORDER BY {order_by}"
            )
            result = await session.execute(statement, params)
            rows = result.mappings().all()
            return [self._row_to_snapshot(cast(Mapping[str, Any], row)) for row in rows]

    async def cancel_stale_running(self) -> int:
        """Mark all tasks stuck in 'running' as 'cancelled'.

        Called at startup to clean up orphaned tasks from a prior restart.
        Returns the number of rows updated.
        """
        async with self._session_factory() as session:
            columns = await self._get_columns(session)
            if "status" not in columns:
                return 0

            now = datetime.now(timezone.utc)
            stmt = text(
                "UPDATE task_runs SET status = 'cancelled', updated_at = :now "
                "WHERE status = 'running'"
            )
            result = await session.execute(stmt, {"now": now})
            await session.commit()
            return int(cast(CursorResult[object], result).rowcount or 0)

    async def _get_columns(self, session: AsyncSession) -> set[str]:
        if "task_runs" in _column_cache:
            return _column_cache["task_runs"]

        def _load_columns(sync_session: SyncSession) -> set[str]:
            bind = sync_session.get_bind()
            inspector = sa.inspect(bind)
            if not inspector.has_table("task_runs"):
                return set()
            return {str(column["name"]) for column in inspector.get_columns("task_runs")}

        columns = await session.run_sync(_load_columns)
        _column_cache["task_runs"] = columns
        return columns

    async def _ensure_task_row(self, session: AsyncSession, task_id: str) -> None:
        await session.execute(
            text("INSERT INTO task_runs (id) VALUES (:task_id) ON CONFLICT(id) DO NOTHING"),
            {"task_id": task_id},
        )

    async def _update_task_row(
        self,
        session: AsyncSession,
        task_id: str,
        values: Mapping[str, object],
    ) -> None:
        set_clauses = ", ".join(f"{column} = :{column}" for column in values)
        statement = text(f"UPDATE task_runs SET {set_clauses} WHERE id = :task_id")
        params = {"task_id": task_id, **values}
        await session.execute(statement, params)

    def _row_to_snapshot(self, row: Mapping[str, Any]) -> TaskRunSnapshot:
        node_summary_raw = row.get("node_summary_json")
        results_raw = row.get("results_json")
        input_files_raw = row.get("input_files_json")
        workflow_raw = row.get("workflow_json")

        return TaskRunSnapshot(
            task_id=str(row["id"]),
            status=self._as_optional_str(row.get("status")),
            workflow_id=self._as_optional_str(row.get("workflow_id")),
            workflow_name=self._as_optional_str(row.get("workflow_name")),
            run_name=self._as_optional_str(row.get("run_name")),
            source=self._as_optional_str(row.get("source")),
            workspace_id=self._as_optional_str(row.get("workspace_id")),
            evaluation_run_id=self._as_optional_str(row.get("evaluation_run_id")),
            created_at=self._parse_datetime(row.get("created_at")),
            completed_at=self._parse_datetime(row.get("completed_at")),
            duration_ms=self._as_optional_int(row.get("duration_ms")),
            node_summary=self._parse_node_summary(node_summary_raw),
            result_preview=self._as_optional_str(row.get("result_preview")),
            results=self._parse_results(results_raw),
            error=self._as_optional_str(row.get("error")),
            dag_hash=self._as_optional_str(row.get("dag_hash")),
            input_files=self._parse_input_files(input_files_raw),
            workflow=self._parse_workflow(workflow_raw),
            updated_at=self._parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _to_json(value: object) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _parse_node_summary(value: object) -> dict[str, int] | None:
        parsed = TaskRunRepository._parse_json(value)
        if not isinstance(parsed, dict):
            return None

        summary: dict[str, int] = {}
        for key, item in parsed.items():
            if isinstance(item, int):
                summary[str(key)] = item
        return summary

    @staticmethod
    def _parse_results(value: object) -> list[dict[str, Any]] | None:
        parsed = TaskRunRepository._parse_json(value)
        if not isinstance(parsed, list):
            return None

        results: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                results.append(dict(item))
        return results

    @staticmethod
    def _parse_input_files(value: object) -> list[dict[str, Any]] | None:
        parsed = TaskRunRepository._parse_json(value)
        if not isinstance(parsed, list):
            return None

        files: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                files.append(dict(item))
        return files

    @staticmethod
    def _parse_workflow(value: object) -> dict[str, Any] | None:
        parsed = TaskRunRepository._parse_json(value)
        if isinstance(parsed, dict):
            return dict(parsed)
        return None

    @staticmethod
    def _parse_json(value: object) -> object:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return None
        if not value.strip():
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

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
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
