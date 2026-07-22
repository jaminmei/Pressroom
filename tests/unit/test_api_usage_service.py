from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.repositories.api_invocation_repository import ApiInvocationRecord
from app.services.api_usage_service import ApiUsageService


def _record(
    record_id: str,
    *,
    workflow_run_id: str | None = None,
    workflow_status: str = "succeeded",
    response_time_ms: int | None = 100,
    storage_bytes: int = 0,
    created_at: datetime | None = None,
) -> ApiInvocationRecord:
    now = created_at or datetime.now(UTC)
    return ApiInvocationRecord(
        id=record_id,
        workflow_id="wf_usage",
        workflow_run_id=workflow_run_id,
        api_key_id="key_1",
        api_key_prefix="dca_test",
        api_key_description=None,
        endpoint_kind="json_run",
        http_status=200,
        workflow_status=workflow_status,
        response_time_ms=response_time_ms,
        input_metadata={"mode": "json"},
        error=None,
        storage_bytes=storage_bytes,
        created_at=now,
        finished_at=now,
        updated_at=now,
    )


class _FakeRepo:
    def __init__(self, records: list[ApiInvocationRecord], storage_used: int = 0) -> None:
        self.records = records
        self.storage_used_value = storage_used
        self.deleted: list[str] = []
        self.retention_exclude: str | None = None
        self.list_params: dict[str, Any] | None = None

    async def list_for_summary(
        self,
        *,
        workflow_id: str,
        start_at: datetime | None,
        workspace_id: str | None = None,
    ) -> list[ApiInvocationRecord]:
        assert workflow_id == "wf_usage"
        assert workspace_id is None
        return [
            record for record in self.records if start_at is None or record.created_at >= start_at
        ]

    async def list_by_workflow(self, **kwargs: Any) -> tuple[list[ApiInvocationRecord], int]:
        self.list_params = kwargs
        return self.records, len(self.records)

    async def storage_used(self, workflow_id: str, *, workspace_id: str | None = None) -> int:
        assert workflow_id == "wf_usage"
        assert workspace_id is None
        return self.storage_used_value

    async def list_retention_candidates(
        self,
        *,
        workflow_id: str,
        exclude_invocation_id: str,
        workspace_id: str | None = None,
    ) -> list[ApiInvocationRecord]:
        assert workflow_id == "wf_usage"
        assert workspace_id is None
        self.retention_exclude = exclude_invocation_id
        return [record for record in self.records if record.id != exclude_invocation_id]

    async def delete_invocation_and_run(self, record: ApiInvocationRecord) -> None:
        self.deleted.append(record.id)


class _FakeStorage:
    tasks_root = "/tmp/nonexistent-api-usage-test"

    def __init__(self) -> None:
        self.deleted_tasks: list[str] = []

    async def delete_task(self, task_id: str) -> None:
        self.deleted_tasks.append(task_id)


@pytest.mark.asyncio()
async def test_api_usage_summary_computes_kpis_and_trend() -> None:
    now = datetime.now(UTC)
    repo = _FakeRepo(
        [
            _record("api_inv_1", response_time_ms=100, created_at=now - timedelta(days=1)),
            _record("api_inv_2", response_time_ms=200, created_at=now - timedelta(days=1)),
            _record("api_inv_3", workflow_status="failed", response_time_ms=1000, created_at=now),
        ],
        storage_used=2048,
    )
    service = ApiUsageService(
        repository=repo,  # type: ignore[arg-type]
        settings=SimpleNamespace(api_usage_retention_max_bytes_per_workflow=4096),  # type: ignore[arg-type]
        storage=_FakeStorage(),  # type: ignore[arg-type]
    )

    summary = await service.summary("wf_usage", "7d")

    assert summary["calls"] == 3
    assert summary["success_rate"] == 0.6667
    assert summary["avg_response_time_ms"] == 433
    assert summary["p95_response_time_ms"] == 1000
    assert summary["failures"] == 1
    assert summary["storage_used_bytes"] == 2048
    assert summary["storage_over_limit"] is False
    assert summary["trend"][-1]["calls"] == 1
    assert summary["trend"][-1]["failures"] == 1


@pytest.mark.asyncio()
async def test_api_usage_list_runs_passes_filters_and_pagination() -> None:
    repo = _FakeRepo([_record("api_inv_1")])
    service = ApiUsageService(
        repository=repo,  # type: ignore[arg-type]
        settings=SimpleNamespace(api_usage_retention_max_bytes_per_workflow=4096),  # type: ignore[arg-type]
        storage=_FakeStorage(),  # type: ignore[arg-type]
    )

    response = await service.list_runs(
        workflow_id="wf_usage",
        range_value="24h",
        status="failed",
        api_key_id="key_1",
        endpoint_kind="file_upload",
        page=2,
        limit=20,
    )

    assert response["meta"] == {"total": 1, "page": 2, "limit": 20}
    assert response["data"][0]["id"] == "api_inv_1"
    assert repo.list_params is not None
    assert repo.list_params["status"] == "failed"
    assert repo.list_params["api_key_id"] == "key_1"
    assert repo.list_params["endpoint_kind"] == "file_upload"
    assert repo.list_params["limit"] == 20
    assert repo.list_params["offset"] == 20


@pytest.mark.asyncio()
async def test_api_usage_retention_deletes_oldest_candidate_and_excludes_current() -> None:
    repo = _FakeRepo(
        [
            _record("api_inv_old", workflow_run_id="task_old", storage_bytes=70),
            _record("api_inv_current", workflow_run_id="task_current", storage_bytes=90),
        ],
        storage_used=150,
    )
    storage = _FakeStorage()
    service = ApiUsageService(
        repository=repo,  # type: ignore[arg-type]
        settings=SimpleNamespace(api_usage_retention_max_bytes_per_workflow=100),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )

    await service.enforce_retention(
        workflow_id="wf_usage",
        exclude_invocation_id="api_inv_current",
    )

    assert repo.retention_exclude == "api_inv_current"
    assert repo.deleted == ["api_inv_old"]
    assert storage.deleted_tasks == ["task_old"]
