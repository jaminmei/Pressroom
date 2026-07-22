"""Repository for API Forward invocation usage records."""

from __future__ import annotations

import json
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
class ApiInvocationRecord:
    id: str
    workflow_id: str
    workflow_run_id: str | None
    api_key_id: str | None
    api_key_prefix: str | None
    api_key_description: str | None
    endpoint_kind: str
    http_status: int | None
    workflow_status: str
    response_time_ms: int | None
    input_metadata: dict[str, Any] | None
    error: dict[str, Any] | None
    storage_bytes: int
    created_at: datetime
    finished_at: datetime | None
    updated_at: datetime
    result_preview: str | None = None
    task_status: str | None = None
    completed_at: datetime | None = None
    workspace_id: str | None = None


def _parse_json(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _row_to_record(row: Mapping[str, Any]) -> ApiInvocationRecord:
    return ApiInvocationRecord(
        id=str(row["id"]),
        workflow_id=str(row["workflow_id"]),
        workflow_run_id=str(row["workflow_run_id"]) if row.get("workflow_run_id") else None,
        api_key_id=str(row["api_key_id"]) if row.get("api_key_id") else None,
        api_key_prefix=str(row["api_key_prefix"]) if row.get("api_key_prefix") else None,
        api_key_description=(
            str(row["api_key_description"]) if row.get("api_key_description") else None
        ),
        endpoint_kind=str(row["endpoint_kind"]),
        http_status=_as_optional_int(row.get("http_status")),
        workflow_status=str(row["workflow_status"]),
        response_time_ms=_as_optional_int(row.get("response_time_ms")),
        input_metadata=_parse_json(row.get("input_metadata_json")),
        error=_parse_json(row.get("error_json")),
        storage_bytes=int(row.get("storage_bytes") or 0),
        created_at=_parse_datetime(row.get("created_at")) or datetime.now(timezone.utc),
        finished_at=_parse_datetime(row.get("finished_at")),
        updated_at=_parse_datetime(row.get("updated_at")) or datetime.now(timezone.utc),
        result_preview=str(row["result_preview"]) if row.get("result_preview") else None,
        task_status=str(row["task_status"]) if row.get("task_status") else None,
        completed_at=_parse_datetime(row.get("completed_at")),
        workspace_id=str(row["workspace_id"]) if row.get("workspace_id") else None,
    )


class ApiInvocationRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create(
        self,
        *,
        id: str,
        workflow_id: str,
        workspace_id: str | None,
        workflow_run_id: str | None,
        api_key_id: str | None,
        api_key_prefix: str | None,
        endpoint_kind: str,
        http_status: int | None,
        workflow_status: str,
        response_time_ms: int | None,
        input_metadata: Mapping[str, Any] | None,
        error: Mapping[str, Any] | None,
        storage_bytes: int,
        created_at: datetime,
        finished_at: datetime | None,
        updated_at: datetime,
    ) -> ApiInvocationRecord:
        workspace_filter = "" if workspace_id is None else "AND workspace_id = :workspace_id"
        async with self._session_factory() as session:
            stmt = text(
                f"""
                INSERT INTO api_invocations (
                    id, workflow_id, workspace_id, workflow_run_id, api_key_id, api_key_prefix,
                    endpoint_kind, http_status, workflow_status, response_time_ms,
                    input_metadata_json, error_json, storage_bytes,
                    created_at, finished_at, updated_at
                )
                SELECT
                    :id, :workflow_id, :workspace_id, :workflow_run_id,
                    :api_key_id, :api_key_prefix,
                    :endpoint_kind, :http_status, :workflow_status, :response_time_ms,
                    :input_metadata_json, :error_json, :storage_bytes,
                    :created_at, :finished_at, :updated_at
                FROM workflows
                WHERE id = :workflow_id
                  {workspace_filter}
                RETURNING id, workflow_id, workflow_run_id, api_key_id, api_key_prefix,
                          NULL AS api_key_description, endpoint_kind, http_status,
                          workflow_status, response_time_ms, input_metadata_json,
                          error_json, storage_bytes, created_at, finished_at,
                          updated_at, NULL AS result_preview, NULL AS task_status,
                          NULL AS completed_at, workspace_id
                """
            )
            result = await session.execute(
                stmt,
                {
                    "id": id,
                    "workflow_id": workflow_id,
                    "workspace_id": workspace_id,
                    "workflow_run_id": workflow_run_id,
                    "api_key_id": api_key_id,
                    "api_key_prefix": api_key_prefix,
                    "endpoint_kind": endpoint_kind,
                    "http_status": http_status,
                    "workflow_status": workflow_status,
                    "response_time_ms": response_time_ms,
                    "input_metadata_json": self._to_json(input_metadata),
                    "error_json": self._to_json(error),
                    "storage_bytes": max(storage_bytes, 0),
                    "created_at": created_at,
                    "finished_at": finished_at,
                    "updated_at": updated_at,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise LookupError(workflow_id)
            await session.commit()
            return _row_to_record(cast(Mapping[str, Any], row))

    async def list_by_workflow(
        self,
        *,
        workflow_id: str,
        start_at: datetime | None,
        status: str | None,
        api_key_id: str | None,
        endpoint_kind: str | None,
        limit: int,
        offset: int,
        workspace_id: str | None = None,
    ) -> tuple[list[ApiInvocationRecord], int]:
        _require_workspace_filter(workspace_id)
        where, params = self._build_filters(
            workflow_id=workflow_id,
            start_at=start_at,
            status=status,
            api_key_id=api_key_id,
            endpoint_kind=endpoint_kind,
            workspace_id=workspace_id,
        )
        async with self._session_factory() as session:
            total_result = await session.execute(
                text(f"SELECT COUNT(*) FROM api_invocations i {where}"),
                params,
            )
            total = int(total_result.scalar() or 0)
            result = await session.execute(
                text(
                    """
                    SELECT
                        i.id, i.workflow_id, i.workflow_run_id, i.api_key_id,
                        i.api_key_prefix, ak.description AS api_key_description,
                        i.endpoint_kind, i.http_status, i.workflow_status,
                        i.response_time_ms, i.input_metadata_json, i.error_json,
                        i.storage_bytes, i.created_at, i.finished_at, i.updated_at,
                        tr.result_preview, tr.status AS task_status,
                        tr.completed_at, w.workspace_id
                    FROM api_invocations i
                    LEFT JOIN workflows w ON w.id = i.workflow_id
                    LEFT JOIN api_keys ak ON ak.id = i.api_key_id
                    LEFT JOIN task_runs tr ON tr.id = i.workflow_run_id
                    """
                    f"{where} "
                    "ORDER BY i.created_at DESC, i.id DESC LIMIT :limit OFFSET :offset"
                ),
                {**params, "limit": limit, "offset": offset},
            )
            rows = result.mappings().all()
            return [_row_to_record(cast(Mapping[str, Any], row)) for row in rows], total

    async def list_for_summary(
        self,
        *,
        workflow_id: str,
        start_at: datetime | None,
        workspace_id: str | None = None,
    ) -> list[ApiInvocationRecord]:
        _require_workspace_filter(workspace_id)
        where, params = self._build_filters(
            workflow_id=workflow_id,
            start_at=start_at,
            status=None,
            api_key_id=None,
            endpoint_kind=None,
            workspace_id=workspace_id,
        )
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        i.id, i.workflow_id, i.workflow_run_id, i.api_key_id,
                        i.api_key_prefix, NULL AS api_key_description,
                        i.endpoint_kind, i.http_status, i.workflow_status,
                        i.response_time_ms, i.input_metadata_json, i.error_json,
                        i.storage_bytes, i.created_at, i.finished_at, i.updated_at,
                        NULL AS result_preview, NULL AS task_status,
                        NULL AS completed_at, w.workspace_id
                    FROM api_invocations i
                    LEFT JOIN workflows w ON w.id = i.workflow_id
                    """
                    f"{where} ORDER BY i.created_at ASC, i.id ASC"
                ),
                params,
            )
            rows = result.mappings().all()
            return [_row_to_record(cast(Mapping[str, Any], row)) for row in rows]

    async def get_by_run(
        self,
        *,
        workflow_id: str,
        workflow_run_id: str,
        workspace_id: str | None = None,
    ) -> ApiInvocationRecord | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        i.id, i.workflow_id, i.workflow_run_id, i.api_key_id,
                        i.api_key_prefix, ak.description AS api_key_description,
                        i.endpoint_kind, i.http_status, i.workflow_status,
                        i.response_time_ms, i.input_metadata_json, i.error_json,
                        i.storage_bytes, i.created_at, i.finished_at, i.updated_at,
                        tr.result_preview, tr.status AS task_status, tr.completed_at,
                        w.workspace_id
                    FROM api_invocations i
                    LEFT JOIN workflows w ON w.id = i.workflow_id
                    LEFT JOIN api_keys ak ON ak.id = i.api_key_id
                    LEFT JOIN task_runs tr ON tr.id = i.workflow_run_id
                    WHERE i.workflow_id = :workflow_id
                      AND i.workflow_run_id = :workflow_run_id
                      AND i.workflow_id IN (
                          SELECT id FROM workflows WHERE workspace_id = :workspace_id
                      )
                    ORDER BY i.created_at DESC LIMIT 1
                    """
                ),
                {
                    "workflow_id": workflow_id,
                    "workflow_run_id": workflow_run_id,
                    "workspace_id": workspace_id,
                },
            )
            row = result.mappings().first()
            return _row_to_record(cast(Mapping[str, Any], row)) if row else None

    async def storage_used(self, workflow_id: str, *, workspace_id: str | None = None) -> int:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COALESCE(SUM(storage_bytes), 0) "
                    "FROM api_invocations WHERE workflow_id = :workflow_id"
                    " AND workflow_id IN ("
                    "SELECT id FROM workflows WHERE workspace_id = :workspace_id"
                    ")"
                ),
                {"workflow_id": workflow_id, "workspace_id": workspace_id},
            )
            return int(result.scalar() or 0)

    async def list_retention_candidates(
        self,
        *,
        workflow_id: str,
        exclude_invocation_id: str,
        workspace_id: str | None = None,
    ) -> list[ApiInvocationRecord]:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        i.id, i.workflow_id, i.workflow_run_id, i.api_key_id,
                        i.api_key_prefix, NULL AS api_key_description,
                        i.endpoint_kind, i.http_status, i.workflow_status,
                        i.response_time_ms, i.input_metadata_json, i.error_json,
                        i.storage_bytes, i.created_at, i.finished_at, i.updated_at,
                        NULL AS result_preview, NULL AS task_status,
                        NULL AS completed_at, w.workspace_id
                    FROM api_invocations i
                    LEFT JOIN workflows w ON w.id = i.workflow_id
                    WHERE i.workflow_id = :workflow_id
                      AND i.id != :exclude_invocation_id
                      AND i.workflow_id IN (
                          SELECT id FROM workflows WHERE workspace_id = :workspace_id
                      )
                      AND i.workflow_status NOT IN ('pending', 'running')
                    ORDER BY i.created_at ASC, i.id ASC
                    """
                ),
                {
                    "workflow_id": workflow_id,
                    "exclude_invocation_id": exclude_invocation_id,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
            return [_row_to_record(cast(Mapping[str, Any], row)) for row in rows]

    async def delete_invocation_and_run(
        self, record: ApiInvocationRecord, *, workspace_id: str | None = None
    ) -> None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            if record.workflow_run_id:
                await session.execute(
                    text(
                        "DELETE FROM task_event_logs WHERE task_run_id = :run_id "
                        "AND EXISTS (SELECT 1 FROM task_runs "
                        "WHERE id = :run_id AND workspace_id = :workspace_id)"
                    ),
                    {"run_id": record.workflow_run_id, "workspace_id": workspace_id},
                )
                await session.execute(
                    text(
                        "DELETE FROM execution_events WHERE workflow_run_id = :run_id "
                        "AND EXISTS (SELECT 1 FROM task_runs "
                        "WHERE id = :run_id AND workspace_id = :workspace_id)"
                    ),
                    {"run_id": record.workflow_run_id, "workspace_id": workspace_id},
                )
                if await self._has_table(session, "node_runs"):
                    await session.execute(
                        text(
                            "DELETE FROM node_runs WHERE task_run_id = :run_id "
                            "AND EXISTS (SELECT 1 FROM task_runs "
                            "WHERE id = :run_id AND workspace_id = :workspace_id)"
                        ),
                        {"run_id": record.workflow_run_id, "workspace_id": workspace_id},
                    )
                await session.execute(
                    text(
                        "DELETE FROM task_runs WHERE id = :run_id "
                        "AND COALESCE(source, 'api_forward') != 'manual' "
                        "AND workspace_id = :workspace_id"
                    ),
                    {"run_id": record.workflow_run_id, "workspace_id": workspace_id},
                )
            await session.execute(
                text(
                    "DELETE FROM api_invocations WHERE id = :id "
                    "AND workflow_id IN ("
                    "SELECT id FROM workflows WHERE workspace_id = :workspace_id)"
                ),
                {"id": record.id, "workspace_id": workspace_id},
            )
            await session.commit()

    @staticmethod
    async def _has_table(session: AsyncSession, table_name: str) -> bool:
        def _inspect(sync_session: SyncSession) -> bool:
            bind = sync_session.get_bind()
            return bool(sa.inspect(bind).has_table(table_name))

        return bool(await session.run_sync(_inspect))

    @staticmethod
    def _build_filters(
        *,
        workflow_id: str,
        start_at: datetime | None,
        status: str | None,
        api_key_id: str | None,
        endpoint_kind: str | None,
        workspace_id: str | None,
    ) -> tuple[str, dict[str, object]]:
        clauses = ["i.workflow_id = :workflow_id"]
        params: dict[str, object] = {"workflow_id": workflow_id}
        if workspace_id is not None:
            clauses.append(
                "i.workflow_id IN (SELECT id FROM workflows WHERE workspace_id = :workspace_id)"
            )
            params["workspace_id"] = workspace_id
        if start_at is not None:
            clauses.append("i.created_at >= :start_at")
            params["start_at"] = start_at
        if status:
            clauses.append("i.workflow_status = :status")
            params["status"] = status
        if api_key_id:
            clauses.append("i.api_key_id = :api_key_id")
            params["api_key_id"] = api_key_id
        if endpoint_kind:
            clauses.append("i.endpoint_kind = :endpoint_kind")
            params["endpoint_kind"] = endpoint_kind
        return f"WHERE {' AND '.join(clauses)}", params

    @staticmethod
    def _to_json(value: Mapping[str, Any] | None) -> str | None:
        if value is None:
            return None
        return json.dumps(dict(value), ensure_ascii=False)
