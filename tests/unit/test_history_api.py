from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import app
from app.models.output import OutputMetadata
from app.models.task import TaskResult
from app.models.workflow import WorkflowDefinition, WorkflowNode
from app.repositories.task_run_repository import TaskRunSnapshot
from tests._api_workspace_contract import (
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


class _HistoryItemStub(BaseModel):
    task_id: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    node_summary: dict[str, int]
    result_preview: str


def _build_result(*, result_id: str, content: str) -> TaskResult:
    return TaskResult(
        result_id=result_id,
        format="markdown",
        filename=f"{result_id}.md",
        content_type="text/markdown",
        storage_path=f"/tmp/{result_id}.md",
        download_url=f"/api/tasks/task-step6/results/{result_id}/download",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=120,
            page_count=1,
            char_count=len(content),
            word_count=max(len(content.split()), 1),
            source_filename="input.txt",
        ),
    )


def _completed_context(task_id: str, results: list[TaskResult]) -> object:
    now = datetime.now(timezone.utc)
    node_states = {
        f"output_{index}": SimpleNamespace(output=result)
        for index, result in enumerate(results, start=1)
    }
    return SimpleNamespace(
        task_id=task_id,
        status=SimpleNamespace(value="completed"),
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=4321,
        output_format="markdown",
        engine="ocr",
        run_name=None,
        progress=SimpleNamespace(
            total_nodes=len(results),
            completed_nodes=len(results),
            failed_nodes=0,
            skipped_nodes=0,
        ),
        result=results[0] if results else None,
        node_states=node_states,
        error=None,
    )


def _running_context(task_id: str, results: list[TaskResult]) -> object:
    now = datetime.now(timezone.utc)
    node_states = {
        "engine_1": SimpleNamespace(
            node_id="engine_1",
            node_type="engine/ocr",
            status=SimpleNamespace(value="running"),
            started_at=now,
            completed_at=None,
            error=None,
            progress=None,
            output=results[0] if results else None,
        )
    }
    return SimpleNamespace(
        task_id=task_id,
        workspace_id=TEST_WORKSPACE_ID,
        status=SimpleNamespace(value="running"),
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=None,
        duration_ms=None,
        output_format="markdown",
        engine="ocr",
        run_name=None,
        progress=SimpleNamespace(
            model_dump=lambda mode="json": {
                "total_nodes": 1,
                "completed_nodes": 0,
                "failed_nodes": 0,
                "pending_nodes": 1,
                "current_node": "engine_1",
                "percentage": 0,
            }
        ),
        result=results[0] if results else None,
        node_states=node_states,
        error=None,
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    install_authenticated_workspace(app, monkeypatch)
    app.state.running_tasks = {}
    app.state.event_store = SimpleNamespace(
        compute_state=lambda _run_id: {},
        get_events=lambda _run_id: [],
    )
    app.state.task_orchestrator = SimpleNamespace(get_task=lambda _task_id: None)
    try:
        yield TestClient(app)
    finally:
        app.state.running_tasks = {}
        remove_authenticated_workspace(app)


def test_results_endpoint_truncates_result_preview_to_500_chars(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-history-preview-500"
    long_content = "A" * 620

    # The endpoint reads running_tasks from app.state and falls through to snapshot path.
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    duration_ms=120,
                    results=[
                        {
                            "result_id": "res_001",
                            "node_id": "engine_1",
                            "node_type": "engine/ocr",
                            "output_format": "markdown",
                            "content": long_content,
                            "file": {
                                "filename": "output.md",
                                "content_type": "text/markdown",
                                "storage_path": "/tmp/output.md",
                                "download_url": f"/api/tasks/{task_id}/results/res_001/download",
                            },
                            "metadata": {"processing_time_ms": 120},
                        }
                    ],
                )
            ),
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    preview = payload["results"][0]["result_preview"]
    assert preview == long_content[:500]
    assert len(preview) == 500


def test_results_endpoint_includes_step6_required_fields(monkeypatch, client: TestClient) -> None:
    task_id = "task-history-results-fields"

    # The endpoint reads running_tasks from app.state and falls through to snapshot path.
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    duration_ms=120,
                    results=[
                        {
                            "result_id": "res_002",
                            "node_id": "engine_1",
                            "node_type": "engine/ocr",
                            "output_format": "markdown",
                            "content": "from ocr result",
                            "file": {
                                "filename": "output.md",
                                "content_type": "text/markdown",
                                "storage_path": "/tmp/output.md",
                                "download_url": f"/api/tasks/{task_id}/results/res_002/download",
                            },
                            "metadata": {"processing_time_ms": 120},
                        },
                        {
                            "result_id": "res_001",
                            "node_id": "engine_2",
                            "node_type": "engine/vlm",
                            "output_format": "markdown",
                            "content": "from vlm result",
                            "file": {
                                "filename": "output2.md",
                                "content_type": "text/markdown",
                                "storage_path": "/tmp/output2.md",
                                "download_url": f"/api/tasks/{task_id}/results/res_001/download",
                            },
                            "metadata": {"processing_time_ms": 90},
                        },
                    ],
                )
            ),
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["status"] == "completed"

    required_result_fields = {
        "result_id",
        "engine_type",
        "output_format",
        "result_preview",
        "duration_ms",
    }

    assert len(payload["results"]) == 2
    for item in payload["results"]:
        assert required_result_fields.issubset(item.keys())
        assert len(item["result_preview"]) <= 500


def test_history_endpoint_includes_result_preview_and_core_fields(
    monkeypatch, client: TestClient
) -> None:
    now = datetime.now(timezone.utc)

    # The endpoint reads running_tasks from app.state and uses task_run_repository.list_snapshots().
    snapshot = TaskRunSnapshot(
        task_id="task-history-item-001",
        workspace_id=TEST_WORKSPACE_ID,
        status="completed",
        workflow_id="wf_001",
        workflow_name="Step6 Workflow",
        created_at=now,
        completed_at=now,
        duration_ms=2048,
        node_summary={"total": 3, "completed": 3, "failed": 0},
        result_preview="preview text",
    )

    async def _list_snapshots_stub(
        *,
        status: str = "all",
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ):
        assert workspace_id == TEST_WORKSPACE_ID
        _ = (status, workflow_id)
        return [snapshot]

    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(list_snapshots=_list_snapshots_stub),
    )

    response = client.get("/api/tasks/history?page=1&limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["meta"]["total"] == 1

    history_item = payload["data"][0]
    required_history_fields = {
        "task_id",
        "workflow_id",
        "workflow_name",
        "status",
        "created_at",
        "completed_at",
        "duration_ms",
        "node_summary",
        "result_preview",
    }
    assert required_history_fields.issubset(history_item.keys())


def test_history_endpoint_handles_mixed_timezone_created_at_without_500(
    monkeypatch, client: TestClient
) -> None:
    aware_now = datetime.now(timezone.utc)
    naive_now = aware_now.replace(tzinfo=None)

    # The endpoint reads running_tasks from app.state and uses task_run_repository.list_snapshots().
    # Return two snapshots: one with aware datetime, one with naive datetime.
    async def _list_snapshots_stub(
        *,
        status: str = "all",
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ):
        assert workspace_id == TEST_WORKSPACE_ID
        _ = (status, workflow_id)
        return [
            TaskRunSnapshot(
                task_id="task-history-aware",
                workspace_id=TEST_WORKSPACE_ID,
                status="completed",
                workflow_id="wf-aware",
                workflow_name="Aware Workflow",
                created_at=aware_now,
                completed_at=aware_now,
                duration_ms=1000,
                node_summary={"total": 1, "completed": 1, "failed": 0},
                result_preview="aware",
            ),
            TaskRunSnapshot(
                task_id="task-history-naive",
                workspace_id=TEST_WORKSPACE_ID,
                status="completed",
                workflow_id="wf-naive",
                workflow_name="Naive Workflow",
                created_at=naive_now,
                completed_at=naive_now,
                duration_ms=900,
                node_summary={"total": 1, "completed": 1, "failed": 0},
                result_preview="naive",
            ),
        ]

    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(list_snapshots=_list_snapshots_stub),
    )

    response = client.get("/api/tasks/history?page=1&limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["meta"]["total"] == 2


def test_results_endpoint_returns_409_when_snapshot_status_is_unknown(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-history-unknown-status"
    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status=None,
                    duration_ms=0,
                    results=[],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "TASK_NOT_COMPLETED"
    assert isinstance(payload["trace_id"], str)


def test_status_endpoint_prefers_terminal_snapshot_status_when_runtime_is_running(
    monkeypatch,
    client: TestClient,
) -> None:
    task_id = "task-status-snapshot-terminal"
    now = datetime.now(timezone.utc)

    # Build a minimal workflow with a single node so _reconstruct_node_states works.
    workflow = WorkflowDefinition(
        nodes=[WorkflowNode(id="engine_1", type="engine/ocr", config={})],
        connections=[],
    )

    # Create a RunningTaskContext — the task appears "running" in memory.
    running_ctx = SimpleNamespace(
        task_id=task_id,
        run_id=task_id,
        workspace_id=TEST_WORKSPACE_ID,
        workflow=workflow,
        asyncio_task=SimpleNamespace(cancelled=lambda: False),
        cancel_requested=False,
    )

    # Mock event_store.get_events to return empty list (no events yet).
    mock_event_store = SimpleNamespace(get_events=lambda run_id: [])

    # Mock task_run_repository.get_snapshot to return a "completed" snapshot (ASYNC).
    snapshot = TaskRunSnapshot(
        task_id=task_id,
        workspace_id=TEST_WORKSPACE_ID,
        status="completed",
        completed_at=now,
        updated_at=now,
        created_at=now,
    )

    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(return_value=snapshot),
        ),
    )

    # Inject running_tasks and event_store on app.state before the request.
    app.state.running_tasks = {task_id: running_ctx}
    app.state.event_store = mock_event_store
    response = client.get(f"/api/tasks/{task_id}")

    # Cleanup
    app.state.running_tasks = {}

    assert response.status_code == 200
    payload = response.json()
    # Nodes have no events, so all are PENDING → overall_status = "running".
    # The snapshot augments timestamps: completed_at is populated from the snapshot.
    assert payload["status"] == "running"
    assert payload["completed_at"] is not None


def test_results_endpoint_reads_persisted_snapshot_when_runtime_is_running(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-results-runtime-running-snapshot-completed"
    context = _running_context(task_id, [_build_result(result_id="res_001", content="running")])

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: context),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    duration_ms=120,
                    results=[
                        {
                            "result_id": "res_001",
                            "node_id": "engine_1",
                            "node_type": "engine/ocr",
                            "output_format": "markdown",
                            "content": "persisted output",
                            "file": {
                                "filename": "persisted.md",
                                "content_type": "text/markdown",
                                "storage_path": "/tmp/persisted.md",
                                "download_url": f"/api/tasks/{task_id}/results/res_001/download",
                            },
                            "metadata": {"processing_time_ms": 120},
                        }
                    ],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["result_id"] == "res_001"
    assert payload["results"][0]["engine_type"] == "ocr"


def test_download_result_falls_back_to_persisted_snapshot_after_restart(
    monkeypatch,
    tmp_path,
    client: TestClient,
) -> None:
    task_id = "task-download-persisted"
    result_id = "res_001"
    result_path = tmp_path / "persisted-result.md"
    result_content = "# persisted output\n"
    result_path.write_text(result_content, encoding="utf-8")

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path)),
    )

    class _RepoStub:
        async def get_snapshot(
            self, requested_task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot:
            assert workspace_id == TEST_WORKSPACE_ID
            return TaskRunSnapshot(
                task_id=requested_task_id,
                workspace_id=TEST_WORKSPACE_ID,
                status="completed",
                results=[
                    {
                        "result_id": result_id,
                        "output_format": "markdown",
                        "content": result_content,
                        "metadata": {"processing_time_ms": 10},
                        "file": {
                            "filename": "persisted-result.md",
                            "content_type": "text/markdown",
                            "storage_path": str(result_path),
                            "download_url": f"/api/tasks/{task_id}/results/{result_id}/download",
                        },
                    }
                ],
            )

    monkeypatch.setattr("app.api.tasks.get_task_run_repository", lambda: _RepoStub())

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 200
    assert response.content.decode("utf-8") == result_content


def test_download_result_reads_snapshot_when_runtime_is_running(
    monkeypatch,
    tmp_path,
    client: TestClient,
) -> None:
    task_id = "task-download-running-snapshot-completed"
    result_id = "res_001"
    result_path = tmp_path / "persisted-running.md"
    result_content = "# completed while runtime still running\n"
    result_path.write_text(result_content, encoding="utf-8")
    running_context = _running_context(task_id, [])
    app.state.task_orchestrator = SimpleNamespace(
        get_task=lambda requested_task_id: running_context
    )

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: running_context),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    results=[
                        {
                            "result_id": result_id,
                            "output_format": "markdown",
                            "content": result_content,
                            "metadata": {"processing_time_ms": 10},
                            "file": {
                                "filename": "persisted-running.md",
                                "content_type": "text/markdown",
                                "storage_path": str(result_path),
                                "download_url": (
                                    f"/api/tasks/{task_id}/results/{result_id}/download"
                                ),
                            },
                        }
                    ],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 200
    assert response.content.decode("utf-8") == result_content


def test_results_endpoint_returns_503_when_snapshot_repository_fails(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-results-snapshot-failure"
    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )

    class _RepoStub:
        async def get_snapshot(
            self, requested_task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot:
            assert workspace_id == TEST_WORKSPACE_ID
            _ = requested_task_id
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.api.tasks.get_task_run_repository", lambda: _RepoStub())

    response = client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "TASK_STATE_UNAVAILABLE"
    assert isinstance(payload["trace_id"], str)


def test_download_result_returns_409_when_task_not_completed(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-download-running"
    result_id = "res_001"
    running_context = SimpleNamespace(
        task_id=task_id,
        run_id=task_id,
        workspace_id=TEST_WORKSPACE_ID,
        status=SimpleNamespace(value="running"),
        result=_build_result(result_id=result_id, content="running"),
        node_states={"output_1": SimpleNamespace(output=None)},
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: running_context),
    )
    app.state.running_tasks = {task_id: running_context}
    app.state.task_orchestrator = SimpleNamespace(
        get_task=lambda requested_task_id: running_context
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(get_snapshot=AsyncMock(return_value=None)),
    )

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "TASK_NOT_COMPLETED"
    assert isinstance(payload["trace_id"], str)


def test_download_result_returns_409_when_snapshot_not_completed(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-download-snapshot-running"
    result_id = "res_001"
    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="running",
                    results=[],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "TASK_NOT_COMPLETED"
    assert isinstance(payload["trace_id"], str)


def test_download_result_returns_503_when_snapshot_repository_fails(
    monkeypatch, client: TestClient
) -> None:
    task_id = "task-download-snapshot-failure"
    result_id = "res_001"
    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )

    class _RepoStub:
        def __init__(self) -> None:
            self.calls = 0

        async def get_snapshot(
            self, requested_task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot:
            assert workspace_id == TEST_WORKSPACE_ID
            self.calls += 1
            if self.calls == 1:
                return TaskRunSnapshot(
                    task_id=requested_task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                )
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.api.tasks.get_task_run_repository", lambda: _RepoStub())

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "TASK_STATE_UNAVAILABLE"
    assert isinstance(payload["trace_id"], str)


def test_download_result_returns_404_for_non_file_storage_path(
    monkeypatch, tmp_path, client: TestClient
) -> None:
    task_id = "task-download-dir-path"
    result_id = "res_001"
    result_dir = tmp_path / "result_dir"
    result_dir.mkdir()

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    results=[
                        {
                            "result_id": result_id,
                            "output_format": "markdown",
                            "content": "content",
                            "file": {
                                "filename": "result.md",
                                "content_type": "text/markdown",
                                "storage_path": str(result_dir),
                            },
                        }
                    ],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "RESULT_NOT_FOUND"
    assert isinstance(payload["trace_id"], str)


def test_download_result_supports_flat_snapshot_file_fields(
    monkeypatch, tmp_path, client: TestClient
) -> None:
    task_id = "task-download-flat-fields"
    result_id = "res_001"
    result_path = tmp_path / "flat-result.md"
    result_content = "# flat fields output\n"
    result_path.write_text(result_content, encoding="utf-8")

    monkeypatch.setattr(
        "app.api.tasks.get_task_orchestrator",
        lambda: SimpleNamespace(get_task=lambda requested_task_id: None),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(
        "app.api.tasks.get_task_run_repository",
        lambda: SimpleNamespace(
            get_snapshot=AsyncMock(
                return_value=TaskRunSnapshot(
                    task_id=task_id,
                    workspace_id=TEST_WORKSPACE_ID,
                    status="completed",
                    results=[
                        {
                            "result_id": result_id,
                            "output_format": "markdown",
                            "content": result_content,
                            "filename": "flat-result.md",
                            "content_type": "text/markdown",
                            "storage_path": str(result_path),
                        }
                    ],
                )
            )
        ),
    )

    response = client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 200
    assert response.content.decode("utf-8") == result_content
