"""API Forward usage summary, trace, and retention services."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from app.config import Settings, get_settings
from app.repositories.api_invocation_repository import (
    ApiInvocationRecord,
    ApiInvocationRepository,
)
from app.storage.local import LocalStorageAdapter, get_storage

VALID_RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
SUCCESS_STATUSES = {"succeeded", "completed", "partial_completed"}


def parse_usage_range(value: str | None) -> tuple[str, datetime]:
    key = (value or "7d").strip().lower()
    if key not in VALID_RANGES:
        key = "7d"
    return key, datetime.now(UTC) - VALID_RANGES[key]


def build_invocation_id() -> str:
    return f"api_inv_{uuid4().hex}"


def directory_size_bytes(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            try:
                total += (Path(dirpath) / filename).stat().st_size
            except OSError:
                continue
    return total


class ApiUsageService:
    def __init__(
        self,
        *,
        repository: ApiInvocationRepository | None = None,
        settings: Settings | None = None,
        storage: LocalStorageAdapter | None = None,
    ) -> None:
        self._repository = repository or ApiInvocationRepository()
        self._settings = settings or get_settings()
        self._storage = storage or get_storage()

    async def record_invocation(
        self,
        *,
        workflow_id: str,
        workspace_id: str | None,
        workflow_run_id: str | None,
        api_key_id: str | None,
        api_key_prefix: str | None,
        endpoint_kind: str,
        http_status: int | None,
        workflow_status: str,
        response_time_ms: int | None,
        input_metadata: dict[str, Any] | None,
        error: dict[str, Any] | None,
        storage_bytes: int,
        created_at: datetime,
        finished_at: datetime | None,
    ) -> ApiInvocationRecord:
        now = datetime.now(UTC)
        record = await self._repository.create(
            id=build_invocation_id(),
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            workflow_run_id=workflow_run_id,
            api_key_id=api_key_id,
            api_key_prefix=api_key_prefix,
            endpoint_kind=endpoint_kind,
            http_status=http_status,
            workflow_status=workflow_status,
            response_time_ms=response_time_ms,
            input_metadata=input_metadata,
            error=error,
            storage_bytes=max(storage_bytes, 0),
            created_at=created_at,
            finished_at=finished_at,
            updated_at=now,
        )
        await self.enforce_retention(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            exclude_invocation_id=record.id,
        )
        return record

    async def summary(
        self,
        workflow_id: str,
        range_value: str | None,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        range_key, start_at = parse_usage_range(range_value)
        records = await self._repository.list_for_summary(
            workflow_id=workflow_id,
            start_at=start_at,
            workspace_id=workspace_id,
        )
        response_times = [
            record.response_time_ms
            for record in records
            if isinstance(record.response_time_ms, int)
        ]
        failures = [record for record in records if record.workflow_status not in SUCCESS_STATUSES]
        total = len(records)
        success_count = total - len(failures)
        p95_ms = self._percentile(response_times, 0.95)
        storage_used = await self._repository.storage_used(workflow_id, workspace_id=workspace_id)
        storage_limit = self._settings.api_usage_retention_max_bytes_per_workflow

        return {
            "range": range_key,
            "calls": total,
            "success_rate": round(success_count / total, 4) if total else 0,
            "avg_response_time_ms": round(mean(response_times)) if response_times else 0,
            "p95_response_time_ms": p95_ms,
            "failures": len(failures),
            "storage_used_bytes": storage_used,
            "storage_limit_bytes": storage_limit,
            "storage_over_limit": storage_used > storage_limit,
            "trend": self._build_trend(records, range_key),
        }

    async def list_runs(
        self,
        *,
        workflow_id: str,
        range_value: str | None,
        workspace_id: str | None = None,
        status: str | None,
        api_key_id: str | None,
        endpoint_kind: str | None,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        _, start_at = parse_usage_range(range_value)
        safe_page = max(page, 1)
        safe_limit = min(max(limit, 1), 100)
        records, total = await self._repository.list_by_workflow(
            workflow_id=workflow_id,
            start_at=start_at,
            status=status or None,
            api_key_id=api_key_id or None,
            endpoint_kind=endpoint_kind or None,
            limit=safe_limit,
            offset=(safe_page - 1) * safe_limit,
            workspace_id=workspace_id,
        )
        return {
            "data": [self._serialize_record(record) for record in records],
            "meta": {"total": total, "page": safe_page, "limit": safe_limit},
        }

    async def get_invocation_by_run(
        self, *, workflow_id: str, workflow_run_id: str, workspace_id: str | None = None
    ) -> ApiInvocationRecord | None:
        return await self._repository.get_by_run(
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            workspace_id=workspace_id,
        )

    async def enforce_retention(
        self,
        *,
        workflow_id: str,
        workspace_id: str | None = None,
        exclude_invocation_id: str,
    ) -> None:
        limit = self._settings.api_usage_retention_max_bytes_per_workflow
        used = await self._repository.storage_used(workflow_id, workspace_id=workspace_id)
        if used <= limit:
            return

        candidates = await self._repository.list_retention_candidates(
            workflow_id=workflow_id,
            exclude_invocation_id=exclude_invocation_id,
            workspace_id=workspace_id,
        )
        for candidate in candidates:
            if used <= limit:
                break
            if candidate.workflow_run_id:
                try:
                    await self._storage.delete_task(candidate.workflow_run_id)
                except Exception:
                    pass
            if workspace_id is None:
                await self._repository.delete_invocation_and_run(candidate)
            else:
                await self._repository.delete_invocation_and_run(
                    candidate, workspace_id=workspace_id
                )
            used = max(0, used - max(candidate.storage_bytes, 0))

    def task_storage_bytes(self, task_id: str | None) -> int:
        if not task_id:
            return 0
        return directory_size_bytes(Path(self._storage.tasks_root) / task_id)

    @staticmethod
    def _serialize_record(record: ApiInvocationRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "workflow_id": record.workflow_id,
            "workflow_run_id": record.workflow_run_id,
            "api_key_id": record.api_key_id,
            "api_key_prefix": record.api_key_prefix,
            "api_key_description": record.api_key_description,
            "endpoint_kind": record.endpoint_kind,
            "http_status": record.http_status,
            "workflow_status": record.workflow_status,
            "response_time_ms": record.response_time_ms,
            "input_metadata": record.input_metadata,
            "error": record.error,
            "storage_bytes": record.storage_bytes,
            "created_at": record.created_at.isoformat(),
            "finished_at": record.finished_at.isoformat() if record.finished_at else None,
            "result_preview": record.result_preview,
            "task_status": record.task_status,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    @staticmethod
    def _percentile(values: list[int], percentile: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
        return ordered[index]

    @staticmethod
    def _build_trend(records: list[ApiInvocationRecord], range_key: str) -> list[dict[str, Any]]:
        days = 1 if range_key == "24h" else (30 if range_key == "30d" else 7)
        today = datetime.now(UTC).date()
        buckets: dict[str, list[ApiInvocationRecord]] = defaultdict(list)
        for record in records:
            buckets[record.created_at.date().isoformat()].append(record)
        trend: list[dict[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            key = day.isoformat()
            items = buckets.get(key, [])
            response_times = [
                item.response_time_ms for item in items if isinstance(item.response_time_ms, int)
            ]
            trend.append(
                {
                    "date": key,
                    "calls": len(items),
                    "failures": sum(
                        1 for item in items if item.workflow_status not in SUCCESS_STATUSES
                    ),
                    "avg_response_time_ms": round(mean(response_times)) if response_times else 0,
                }
            )
        return trend
