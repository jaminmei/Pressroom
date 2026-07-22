"""Repository for API key rows stored in api_keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


@dataclass(slots=True)
class ApiKeyRecord:
    id: str
    key_hash: str
    key_prefix: str
    workflow_id: str
    description: str | None
    created_by: str | None
    created_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    last_used_at: datetime | None
    workspace_id: str | None = None


def _row_to_record(row: Any) -> ApiKeyRecord:
    m = row._mapping
    return ApiKeyRecord(
        id=m["id"],
        key_hash=m["key_hash"],
        key_prefix=m["key_prefix"],
        workflow_id=m["workflow_id"],
        description=m.get("description"),
        created_by=m.get("created_by"),
        created_at=m.get("created_at"),
        expires_at=m.get("expires_at"),
        is_active=bool(m["is_active"]),
        last_used_at=m.get("last_used_at"),
        workspace_id=m.get("workspace_id"),
    )


class ApiKeyRepository:
    """Persist and query API keys stored in api_keys."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create(
        self,
        *,
        id: str,
        key_hash: str,
        key_prefix: str,
        workflow_id: str,
        workspace_id: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> ApiKeyRecord:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                """
                INSERT INTO api_keys
                    (id, key_hash, key_prefix, workflow_id, workspace_id,
                      description, created_by, expires_at)
                SELECT
                    :id, :key_hash, :key_prefix, :workflow_id, :workspace_id,
                    :description, :created_by, :expires_at
                FROM workflows
                WHERE id = :workflow_id
                  AND workspace_id = :workspace_id
                RETURNING id, key_hash, key_prefix, workflow_id, description,
                          created_by, created_at, expires_at, is_active, last_used_at,
                          workspace_id
                """
            )
            result = await session.execute(
                stmt,
                {
                    "id": id,
                    "key_hash": key_hash,
                    "key_prefix": key_prefix,
                    "workflow_id": workflow_id,
                    "workspace_id": workspace_id,
                    "description": description,
                    "created_by": created_by,
                    "expires_at": expires_at,
                },
            )
            row = result.first()
            if row is None:
                raise LookupError(workflow_id)
            await session.commit()
            return _row_to_record(row)

    async def get_by_id(
        self,
        id: str,
        *,
        workspace_id: str | None = None,
    ) -> ApiKeyRecord | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "SELECT ak.id, ak.key_hash, ak.key_prefix, ak.workflow_id, "
                "ak.description, ak.created_by, ak.created_at, ak.expires_at, "
                "ak.is_active, ak.last_used_at, w.workspace_id "
                "FROM api_keys ak LEFT JOIN workflows w ON w.id = ak.workflow_id "
                "WHERE ak.id = :id"
                " AND w.workspace_id = :workspace_id"
            )
            result = await session.execute(stmt, {"id": id, "workspace_id": workspace_id})
            row = result.first()
            return _row_to_record(row) if row else None

    async def get_by_hash(
        self,
        key_hash: str,
        *,
        workspace_id: str | None = None,
    ) -> ApiKeyRecord | None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "SELECT ak.id, ak.key_hash, ak.key_prefix, ak.workflow_id, "
                "ak.description, ak.created_by, ak.created_at, ak.expires_at, "
                "ak.is_active, ak.last_used_at, w.workspace_id "
                "FROM api_keys ak LEFT JOIN workflows w ON w.id = ak.workflow_id "
                "WHERE ak.key_hash = :key_hash"
                " AND w.workspace_id = :workspace_id"
            )
            result = await session.execute(
                stmt, {"key_hash": key_hash, "workspace_id": workspace_id}
            )
            row = result.first()
            return _row_to_record(row) if row else None

    async def get_by_hash_for_auth(self, key_hash: str) -> ApiKeyRecord | None:
        async with self._session_factory() as session:
            stmt = text(
                "SELECT ak.id, ak.key_hash, ak.key_prefix, ak.workflow_id, "
                "ak.description, ak.created_by, ak.created_at, ak.expires_at, "
                "ak.is_active, ak.last_used_at, w.workspace_id "
                "FROM api_keys ak LEFT JOIN workflows w ON w.id = ak.workflow_id "
                "WHERE ak.key_hash = :key_hash"
            )
            result = await session.execute(stmt, {"key_hash": key_hash})
            row = result.first()
            return _row_to_record(row) if row else None

    async def list_by_workflow(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[ApiKeyRecord]:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "SELECT ak.id, ak.key_hash, ak.key_prefix, ak.workflow_id, "
                "ak.description, ak.created_by, ak.created_at, ak.expires_at, "
                "ak.is_active, ak.last_used_at, w.workspace_id "
                "FROM api_keys ak LEFT JOIN workflows w ON w.id = ak.workflow_id "
                "WHERE ak.workflow_id = :wid"
                " AND w.workspace_id = :workspace_id"
                " ORDER BY ak.created_at DESC"
            )
            result = await session.execute(stmt, {"wid": workflow_id, "workspace_id": workspace_id})
            return [_row_to_record(row) for row in result.all()]

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        workspace_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[ApiKeyRecord]:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "SELECT ak.id, ak.key_hash, ak.key_prefix, ak.workflow_id, "
                "ak.description, ak.created_by, ak.created_at, ak.expires_at, "
                "ak.is_active, ak.last_used_at, w.workspace_id "
                "FROM api_keys ak LEFT JOIN workflows w ON w.id = ak.workflow_id "
                "WHERE w.workspace_id = :workspace_id"
                " AND (:include_inactive OR ak.is_active IS TRUE)"
                " ORDER BY ak.created_at DESC LIMIT :limit OFFSET :offset"
            )
            result = await session.execute(
                stmt,
                {
                    "limit": limit,
                    "offset": offset,
                    "workspace_id": workspace_id,
                    "include_inactive": include_inactive,
                },
            )
            return [_row_to_record(row) for row in result.all()]

    async def count(
        self,
        *,
        workspace_id: str | None = None,
        include_inactive: bool = True,
    ) -> int:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_keys ak "
                    "LEFT JOIN workflows w ON w.id = ak.workflow_id "
                    "WHERE w.workspace_id = :workspace_id "
                    "AND (:include_inactive OR ak.is_active IS TRUE)"
                ),
                {
                    "workspace_id": workspace_id,
                    "include_inactive": include_inactive,
                },
            )
            return int(result.scalar() or 0)

    async def set_active(
        self,
        id: str,
        is_active: bool,
        *,
        workspace_id: str | None = None,
    ) -> bool:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "UPDATE api_keys SET is_active = :active WHERE id = :id"
                " AND workflow_id IN ("
                "SELECT id FROM workflows WHERE workspace_id = :workspace_id"
                ")"
            )
            result = await session.execute(
                stmt, {"active": is_active, "id": id, "workspace_id": workspace_id}
            )
            await session.commit()
            return cast(CursorResult, result).rowcount > 0

    async def touch_last_used(
        self,
        id: str,
        when: datetime,
        *,
        workspace_id: str | None = None,
    ) -> None:
        _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            stmt = text(
                "UPDATE api_keys SET last_used_at = :when WHERE id = :id"
                " AND workflow_id IN ("
                "SELECT id FROM workflows WHERE workspace_id = :workspace_id"
                ")"
            )
            await session.execute(stmt, {"when": when, "id": id, "workspace_id": workspace_id})
            await session.commit()

    async def touch_last_used_for_auth(self, id: str, when: datetime) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text("UPDATE api_keys SET last_used_at = :when WHERE id = :id"),
                {"when": when, "id": id},
            )
            await session.commit()
