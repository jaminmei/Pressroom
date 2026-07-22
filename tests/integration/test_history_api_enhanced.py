from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories.task_run_repository import TaskRunSnapshot
from tests._api_workspace_contract import TEST_WORKSPACE_ID

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


class _SnapshotRepository:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], TaskRunSnapshot] = {}

    async def seed_task_with_results(
        self,
        *,
        task_id: str,
        status: str,
        duration_ms: int,
        results: list[dict[str, object]],
        workspace_id: str = TEST_WORKSPACE_ID,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._snapshots[(task_id, workspace_id)] = TaskRunSnapshot(
            task_id=task_id,
            status=status,
            workspace_id=workspace_id,
            created_at=now,
            completed_at=now if status == "completed" else None,
            duration_ms=duration_ms,
            result_preview=str(results[0].get("content", ""))[:500] if results else "",
            results=results,
            updated_at=now,
        )

    async def get_snapshot(
        self,
        task_id: str,
        *,
        workspace_id: str | None,
    ) -> TaskRunSnapshot | None:
        if workspace_id is None:
            return None
        return self._snapshots.get((task_id, workspace_id))


@pytest_asyncio.fixture()
async def history_api(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[_SnapshotRepository, AsyncClient]]:
    repository = _SnapshotRepository()
    monkeypatch.setattr("app.api.tasks.get_task_run_repository", lambda: repository)
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(app.state, "event_store", object(), raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield repository, client


def _result(*, result_id: str, content: str, engine_type: str = "ocr") -> dict[str, object]:
    return {
        "result_id": result_id,
        "node_id": f"node_{result_id}",
        "node_type": f"engine/{engine_type}",
        "engine_type": engine_type,
        "output_format": "json",
        "content": content,
        "duration_ms": 200,
        "status": "completed",
    }


@pytest.mark.asyncio
async def test_results_endpoint_returns_multiple_results(
    history_api: tuple[_SnapshotRepository, AsyncClient],
) -> None:
    repository, client = history_api
    task_id = "task-history-multi-results"
    await repository.seed_task_with_results(
        task_id=task_id,
        status="completed",
        duration_ms=3500,
        results=[
            _result(result_id="res_001", content="first output"),
            _result(result_id="res_002", content="second output"),
        ],
    )

    response = await client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert [item["result_id"] for item in payload["results"]] == ["res_001", "res_002"]
    assert payload["summary"]["total_outputs"] == 2


@pytest.mark.asyncio
async def test_results_endpoint_reads_persisted_results_after_restart(
    history_api: tuple[_SnapshotRepository, AsyncClient],
) -> None:
    repository, client = history_api
    task_id = "task-history-persisted-after-restart"
    await repository.seed_task_with_results(
        task_id=task_id,
        status="completed",
        duration_ms=3100,
        results=[
            _result(result_id="res_001", content="ocr content " + ("A" * 580)),
            _result(result_id="res_002", content="vlm content", engine_type="vlm"),
        ],
    )

    response = await client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["status"] == "completed"
    assert len(payload["results"]) == 2

    required_result_fields = {
        "result_id",
        "engine_type",
        "output_format",
        "result_preview",
        "duration_ms",
    }
    for item in payload["results"]:
        assert required_result_fields.issubset(item.keys())
        assert len(item["result_preview"]) <= 500


@pytest.mark.asyncio
async def test_results_endpoint_returns_404_for_unknown_task(
    history_api: tuple[_SnapshotRepository, AsyncClient],
) -> None:
    _, client = history_api

    response = await client.get("/api/tasks/task-history-missing/results")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "TASK_NOT_FOUND"
    assert isinstance(payload["trace_id"], str)


@pytest.mark.asyncio
async def test_results_endpoint_returns_409_for_unfinished_task(
    history_api: tuple[_SnapshotRepository, AsyncClient],
) -> None:
    repository, client = history_api
    task_id = "task-history-not-completed"
    await repository.seed_task_with_results(
        task_id=task_id,
        status="running",
        duration_ms=0,
        results=[],
    )

    response = await client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "TASK_NOT_COMPLETED"
    assert isinstance(payload["trace_id"], str)
