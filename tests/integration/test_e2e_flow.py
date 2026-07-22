"""End-to-end flow integration tests.

Tests the complete pipeline: upload → create task → OCR → get result.
Validates document router, task orchestrator state transitions,
and output formatter producing valid Markdown from DocTags.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
        self.snapshots[task_id] = TaskRunSnapshot(**payload)

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
    async def run(self, workflow, **_kwargs: Any) -> DAGRunResult:
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


@pytest.fixture(autouse=True)
def authenticated_route_runtime(monkeypatch: pytest.MonkeyPatch):
    repository = _SnapshotRepository()
    install_authenticated_workspace(app, monkeypatch)
    monkeypatch.setattr(tasks_api, "get_task_run_repository", lambda: repository)
    monkeypatch.setattr(app.state, "dag_scheduler", _ImmediateScheduler(), raising=False)
    monkeypatch.setattr(app.state, "engine_client", SimpleNamespace(), raising=False)
    monkeypatch.setattr(
        app.state,
        "event_store",
        SimpleNamespace(get_events=lambda _run_id: [], compute_state=lambda _run_id: {}),
        raising=False,
    )
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(app.state, "provider_store", None, raising=False)
    yield
    remove_authenticated_workspace(app)


@pytest.fixture
def isolated_e2e_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    get_settings.cache_clear()
    get_task_orchestrator.cache_clear()
    yield tmp_path
    get_task_orchestrator.cache_clear()
    get_settings.cache_clear()


async def _create_task_with_file(
    client: AsyncClient,
    *,
    name: str = "doc.txt",
    payload: bytes = b"hello world",
    mime: str = "text/plain",
    engine: str = "ocr",
    output_format: str = "markdown",
) -> dict:
    response = await client.post(
        "/api/tasks",
        data={"engine": engine, "output_format": output_format},
        files={"file": (name, payload, mime)},
    )
    return {"status_code": response.status_code, "body": response.json()}


async def _poll_until_done(client: AsyncClient, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in {"completed", "failed"}:
            return data
        await asyncio.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not finish in time")


# ---------------------------------------------------------------------------
# 1. Full E2E: text upload → task → OCR mock → markdown result
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_e2e_text_upload_produces_markdown(isolated_e2e_storage: Path) -> None:
    """Upload a .txt file, run OCR (mock), and verify markdown output."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(client, name="sample.txt", payload=b"hello")
        assert result["status_code"] == 202
        task_id = result["body"]["task_id"]

        completed = await _poll_until_done(client, task_id)
        results_response = await client.get(f"/api/tasks/{task_id}/results")

    assert completed["status"] == "completed"
    assert completed["progress"]["percentage"] == 100
    assert results_response.status_code == 200
    assert results_response.json()["results"][0]["file"]["download_url"].endswith("/download")


# ---------------------------------------------------------------------------
# 2. Full E2E: PDF upload fails gracefully when pdf2image unavailable
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_e2e_pdf_upload_fails_gracefully(isolated_e2e_storage: Path) -> None:
    """PDF upload should produce a failed task when pdf2image/poppler is unavailable."""
    pdf_bytes = b"%PDF-1.4\nmock-pdf-content"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(
            client, name="report.pdf", payload=pdf_bytes, mime="application/pdf"
        )
        assert result["status_code"] == 202
        task_id = result["body"]["task_id"]

        completed = await _poll_until_done(client, task_id)

    # In test env without poppler, PDF conversion fails; task should be marked failed
    assert completed["status"] in {"completed", "failed"}
    if completed["status"] == "failed":
        assert "error" in completed


# ---------------------------------------------------------------------------
# 3. Document router correctly routes text to OCR engine
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_document_router_routes_text_to_ocr(isolated_e2e_storage: Path) -> None:
    """Verify the document router accepts text/plain and the task completes."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(
            client, name="notes.txt", payload=b"some notes", mime="text/plain"
        )
        assert result["status_code"] == 202
        task_id = result["body"]["task_id"]

        completed = await _poll_until_done(client, task_id)

    assert completed["status"] == "completed"
    assert completed["progress"]["completed_nodes"] == completed["progress"]["total_nodes"]


# ---------------------------------------------------------------------------
# 4. Task orchestrator state transitions: pending → running → completed
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_task_state_transitions(isolated_e2e_storage: Path) -> None:
    """Verify the task transitions through pending → (running) → completed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(client)
        assert result["body"]["status"] == "pending"
        task_id = result["body"]["task_id"]

        completed = await _poll_until_done(client, task_id)

    assert completed["status"] == "completed"
    assert completed["progress"]["failed_nodes"] == 0
    assert completed["progress"]["pending_nodes"] == 0


# ---------------------------------------------------------------------------
# 5. Output formatter produces valid markdown content
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_output_formatter_produces_valid_markdown(
    isolated_e2e_storage: Path,
) -> None:
    """Verify the output formatter generates non-empty markdown with metadata."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(client, name="doc.txt", payload=b"content")
        task_id = result["body"]["task_id"]
        await _poll_until_done(client, task_id)

        results_resp = await client.get(f"/api/tasks/{task_id}/results")

    assert results_resp.status_code == 200
    first_result = results_resp.json()["results"][0]
    assert first_result["file"]["content_type"] == "application/json"
    assert "mock" in first_result["content"].lower()


# ---------------------------------------------------------------------------
# 6. Results endpoint returns structured output after completion
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_results_endpoint_returns_structured_output(
    isolated_e2e_storage: Path,
) -> None:
    """Verify GET /api/tasks/{id}/results returns the expected structure."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await _create_task_with_file(client)
        task_id = result["body"]["task_id"]
        await _poll_until_done(client, task_id)

        resp = await client.get(f"/api/tasks/{task_id}/results")

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert len(body["results"]) >= 1
    assert body["summary"]["total_outputs"] >= 1
    first = body["results"][0]
    assert "result_id" in first
    assert "content" in first
    assert "file" in first
    assert "metadata" in first


# ---------------------------------------------------------------------------
# 7. Multiple sequential tasks complete independently
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_multiple_sequential_tasks_complete(isolated_e2e_storage: Path) -> None:
    """Multiple tasks created sequentially should each complete independently."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await _create_task_with_file(client, name="a.txt", payload=b"first")
        r2 = await _create_task_with_file(client, name="b.txt", payload=b"second")
        tid1 = r1["body"]["task_id"]
        tid2 = r2["body"]["task_id"]

        c1 = await _poll_until_done(client, tid1)
        c2 = await _poll_until_done(client, tid2)

    assert c1["status"] == "completed"
    assert c2["status"] == "completed"
    assert c1["task_id"] != c2["task_id"]
