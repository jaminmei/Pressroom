"""API contract integration tests.

Validates that API responses conform to the contract defined in
document/dev/03-api-contract.md — response shapes, status codes,
and error formats.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import tasks as tasks_api
from app.api.tasks import get_task_orchestrator
from app.config import get_settings
from app.main import app
from app.models.execution import NodeOutput
from app.repositories.task_run_repository import TaskRunSnapshot
from app.services.dag_scheduler import DAGRunResult
from tests._api_workspace_contract import (
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


class _SnapshotRepository:
    def __init__(self) -> None:
        self.snapshots: dict[str, TaskRunSnapshot] = {}

    async def upsert_snapshot(self, **values: Any) -> None:
        task_id = str(values["task_id"])
        previous = self.snapshots.get(task_id)
        payload = {
            name: getattr(previous, name) if previous is not None else None
            for name in TaskRunSnapshot.__dataclass_fields__
        }
        payload.update({key: value for key, value in values.items() if key in payload})
        payload["task_id"] = task_id
        if payload["results"] is not None:
            payload["results"] = list(payload["results"])
        self.snapshots[task_id] = TaskRunSnapshot(**cast(Any, payload))

    async def get_snapshot(
        self,
        task_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> TaskRunSnapshot | None:
        snapshot = self.snapshots.get(task_id)
        expected = workspace_id or expected_workspace_id
        if snapshot is None or (expected is not None and snapshot.workspace_id != expected):
            return None
        return snapshot

    async def list_snapshots(
        self,
        *,
        status: str = "all",
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRunSnapshot]:
        return [
            snapshot
            for snapshot in self.snapshots.values()
            if (workspace_id is None or snapshot.workspace_id == workspace_id)
            and (status == "all" or snapshot.status == status)
            and (workflow_id is None or snapshot.workflow_id == workflow_id)
        ]


class _ImmediateScheduler:
    async def run(self, workflow: Any, **_kwargs: Any) -> DAGRunResult:
        return DAGRunResult(
            completed={
                node.id: NodeOutput(
                    text=f"mock output from {node.id}",
                    metadata={"node_type": node.type},
                )
                for node in workflow.nodes
            },
            failed={},
            skipped=set(),
        )


class _RuntimeProviderStore:
    def get_for_runtime(self, provider_id: str, workspace_id: str) -> None:
        _ = (provider_id, workspace_id)
        return None


@pytest.fixture(autouse=True)
def authenticated_route_runtime(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    repository = _SnapshotRepository()
    install_authenticated_workspace(app, monkeypatch)
    monkeypatch.setattr(tasks_api, "get_task_run_repository", lambda: repository)
    monkeypatch.setattr(app.state, "dag_scheduler", _ImmediateScheduler(), raising=False)
    monkeypatch.setattr(app.state, "engine_client", SimpleNamespace(), raising=False)
    monkeypatch.setattr(app.state, "auth_resolver", SimpleNamespace(), raising=False)
    monkeypatch.setattr(
        app.state,
        "event_store",
        SimpleNamespace(get_events=lambda _run_id: [], compute_state=lambda _run_id: {}),
        raising=False,
    )
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(app.state, "provider_store", _RuntimeProviderStore(), raising=False)
    yield
    remove_authenticated_workspace(app)


@pytest.fixture
def isolated_contract_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    get_settings.cache_clear()
    get_task_orchestrator.cache_clear()
    yield tmp_path
    get_task_orchestrator.cache_clear()
    get_settings.cache_clear()


async def _create_and_complete(
    client: AsyncClient,
    *,
    name: str = "doc.txt",
    payload: bytes = b"hello",
    mime: str = "text/plain",
) -> str:
    resp = await client.post(
        "/api/tasks",
        files={"file": (name, payload, mime)},
    )
    task_id = cast(str, resp.json()["task_id"])
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        r = await client.get(f"/api/tasks/{task_id}")
        if r.json()["status"] in {"completed", "failed"}:
            return task_id
        await asyncio.sleep(0.02)
    raise AssertionError("Task did not complete")


# ---------------------------------------------------------------------------
# 1. POST /api/tasks response format (202)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_create_task_response_format(
    isolated_contract_storage: Path,
) -> None:
    """POST /api/tasks must return 202 with task_id, status, created_at."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/tasks",
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"].startswith("task_")
    assert body["status"] == "pending"
    assert "created_at" in body


# ---------------------------------------------------------------------------
# 1.5 POST /api/tasks/node-run response format (202)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_create_node_run_task_response_format(
    isolated_contract_storage: Path,
) -> None:
    """POST /api/tasks/node-run must return 202 with task metadata."""
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "output_1", "type": "output/markdown", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/tasks/node-run",
            data={
                "workflow": json.dumps(workflow),
                "node_id": "engine_1",
                "output_format": "markdown",
            },
            files={"files": ("doc.txt", b"hello", "text/plain")},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"].startswith("task_")
    assert body["status"] == "pending"
    assert body["node_id"] == "engine_1"
    assert body["output_format"] == "markdown"
    assert "created_at" in body


# ---------------------------------------------------------------------------
# 2. GET /api/tasks/{id} response format (200)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_get_task_status_response_format(
    isolated_contract_storage: Path,
) -> None:
    """GET /api/tasks/{id} must include task_id, status, progress, timestamps."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_and_complete(client)
        resp = await client.get(f"/api/tasks/{task_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["status"] in {"pending", "running", "completed", "failed"}
    assert "created_at" in body
    assert "updated_at" in body

    progress = body["progress"]
    assert "total_nodes" in progress
    assert "completed_nodes" in progress
    assert "failed_nodes" in progress
    assert "pending_nodes" in progress
    assert "percentage" in progress


# ---------------------------------------------------------------------------
# 3. GET /api/tasks/{id}/results response format (200)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_get_task_results_response_format(
    isolated_contract_storage: Path,
) -> None:
    """GET /api/tasks/{id}/results must return results array and summary."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_and_complete(client)
        resp = await client.get(f"/api/tasks/{task_id}/results")

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert isinstance(body["results"], list)
    assert len(body["results"]) >= 1

    result = body["results"][0]
    assert "result_id" in result
    assert "file" in result
    assert "filename" in result["file"]
    assert "size_bytes" in result["file"]
    assert "content_type" in result["file"]
    assert "metadata" in result
    assert "content" in result

    summary = body["summary"]
    assert "total_outputs" in summary
    assert "completed" in summary
    assert "failed" in summary


# ---------------------------------------------------------------------------
# 4. Error response format — TASK_NOT_FOUND (404)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_error_response_format_task_not_found(
    isolated_contract_storage: Path,
) -> None:
    """404 errors must follow {error: {code, message}} format."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tasks/task_nonexistent")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "TASK_NOT_FOUND"
    assert isinstance(body["message"], str)
    assert len(body["message"]) > 0
    assert body["trace_id"].startswith("tr-")


# ---------------------------------------------------------------------------
# 5. Error response format — UNSUPPORTED_FILE_TYPE (400)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_error_response_format_unsupported_file(
    isolated_contract_storage: Path,
) -> None:
    """400 errors for unsupported file types must follow error format."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/tasks",
            files={"file": ("bad.zip", b"PK\x03\x04", "application/zip")},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "UNSUPPORTED_FILE_TYPE"
    assert isinstance(body["message"], str)


# ---------------------------------------------------------------------------
# 6. Error response format — EMPTY_FILE (400)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_error_response_format_empty_file(
    isolated_contract_storage: Path,
) -> None:
    """400 errors for empty files must follow error format."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/tasks",
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "EMPTY_FILE"


# ---------------------------------------------------------------------------
# 7. Health endpoint response format
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_health_endpoint_response_format() -> None:
    """GET /api/health must return status, timestamp, version."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "timestamp" in body
    assert "version" in body


# ---------------------------------------------------------------------------
# 8. Upload endpoint response format
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_upload_endpoint_response_format(
    isolated_contract_storage: Path,
) -> None:
    """POST /api/files/upload must return file_id, filename, mime_type, size_bytes."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/files/upload",
            files={"file": ("test.pdf", b"%PDF-1.4\nmock", "application/pdf")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["file_id"].startswith("file_")
    assert body["filename"] == "test.pdf"
    assert body["mime_type"] == "application/pdf"
    assert isinstance(body["size_bytes"], int)
    assert body["size_bytes"] > 0
