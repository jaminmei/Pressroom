from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import tasks as tasks_api
from app.api import workflows as workflows_api
from app.api.task_helpers import build_result_entries_from_context
from app.config import get_settings
from app.main import app
from app.models.output import OutputMetadata
from app.models.task import NodeState, NodeStatus, TaskProgress, TaskResult
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.task_run_repository import TaskRunSnapshot
from app.services.workflow_store import WorkflowStore
from tests._api_workspace_contract import (
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)

_ORIG_GET_TASK_RUN_REPOSITORY = tasks_api.get_task_run_repository
_ORIG_GET_WORKFLOW_STORE = workflows_api.get_workflow_store


def _clear_api_caches() -> None:
    tasks_api.reset_task_orchestrator()
    _ORIG_GET_TASK_RUN_REPOSITORY.cache_clear()
    _ORIG_GET_WORKFLOW_STORE.cache_clear()


def _sample_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={"encoding": "utf-8"}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )


@pytest.fixture(autouse=True)
def authenticated_workspace(monkeypatch: pytest.MonkeyPatch):
    install_authenticated_workspace(app, monkeypatch)
    yield
    remove_authenticated_workspace(app)


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


@pytest.fixture
def snapshot_repository(monkeypatch: pytest.MonkeyPatch) -> _SnapshotRepository:
    repository = _SnapshotRepository()
    monkeypatch.setattr(tasks_api, "get_task_run_repository", lambda: repository)
    return repository


@pytest.fixture
def route_client(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_repository: _SnapshotRepository,
):
    monkeypatch.setattr(app.state, "dag_scheduler", SimpleNamespace(), raising=False)
    monkeypatch.setattr(app.state, "engine_client", SimpleNamespace(), raising=False)
    monkeypatch.setattr(
        app.state,
        "event_store",
        SimpleNamespace(get_events=lambda _run_id: [], compute_state=lambda _run_id: {}),
        raising=False,
    )
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(app.state, "provider_store", None, raising=False)
    monkeypatch.setattr(
        app.state,
        "task_orchestrator",
        SimpleNamespace(get_task=lambda _task_id: None),
        raising=False,
    )
    monkeypatch.setattr(tasks_api, "_start_dag_run", lambda **_kwargs: None)
    client = TestClient(app)
    yield client
    client.close()


def _build_result(
    *,
    task_id: str,
    storage_root: Path,
    result_id: str,
    output_format: str,
    content: str,
) -> TaskResult:
    extension = {"markdown": "md", "plaintext": "txt"}.get(output_format, "txt")
    media_type = {"markdown": "text/markdown", "plaintext": "text/plain"}.get(
        output_format,
        "text/plain",
    )
    result_path = storage_root / f"{result_id}.{extension}"
    result_path.write_text(content, encoding="utf-8")
    return TaskResult(
        result_id=result_id,
        format=output_format,
        filename=result_path.name,
        content_type=media_type,
        storage_path=str(result_path),
        download_url=f"/api/tasks/{task_id}/results/{result_id}/download",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=180,
            page_count=1,
            char_count=len(content),
            word_count=max(len(content.split()), 1),
            source_filename="sample.txt",
        ),
    )


def test_e2e_backend_support_quick_convert_api_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    route_client: TestClient,
    snapshot_repository: _SnapshotRepository,
) -> None:
    _clear_api_caches()
    now = datetime.now(timezone.utc)
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    result = _build_result(
        task_id="task-e2e-quick-001",
        storage_root=storage_root,
        result_id="res-quick-001",
        output_format="markdown",
        content="# Quick Convert",
    )
    context = SimpleNamespace(
        task_id="task-e2e-quick-001",
        workflow=_sample_workflow_definition(),
        status=SimpleNamespace(value="completed"),
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=128,
        engine="text",
        output_format="markdown",
        progress=TaskProgress(
            total_nodes=4,
            completed_nodes=4,
            failed_nodes=0,
            pending_nodes=0,
            skipped_nodes=0,
            percentage=100,
        ),
        node_states={
            "end_1": NodeState(
                node_id="end_1",
                node_type="end/final",
                status=NodeStatus.COMPLETED,
                output={
                    "node_id": "end_1",
                    "status": "completed",
                    "available_result_ids": [result.result_id],
                    "failed_outputs": [],
                },
            ),
            "output_1": NodeState(
                node_id="output_1",
                node_type="output/markdown",
                status=NodeStatus.COMPLETED,
                output=result,
            ),
        },
        result=result,
        error=None,
    )

    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(max_file_size_mb=10, storage_root=str(storage_root)),
    )

    settings = get_settings().model_copy(update={"storage_root": str(tmp_path)})
    monkeypatch.setattr("app.api.tasks.get_settings", lambda: settings)

    create_response = route_client.post(
        "/api/tasks",
        data={"engine": "text", "output_format": "markdown"},
        files={"file": ("quick.txt", b"hello quick", "text/plain")},
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]
    snapshot_repository.snapshots[task_id] = TaskRunSnapshot(
        task_id=task_id,
        status="completed",
        workspace_id=TEST_WORKSPACE_ID,
        created_at=now,
        completed_at=now,
        updated_at=now,
        duration_ms=128,
        node_summary={"completed": 4},
        results=build_result_entries_from_context(context),
    )

    status_response = route_client.get(f"/api/tasks/{task_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    results_response = route_client.get(f"/api/tasks/{task_id}/results")
    assert results_response.status_code == 200
    results_payload = results_response.json()
    assert results_payload["results"][0]["file"]["download_url"] == result.download_url

    download_response = route_client.get(
        f"/api/tasks/{task_id}/results/{result.result_id}/download"
    )
    assert download_response.status_code == 200
    assert download_response.text == "# Quick Convert"


def test_e2e_backend_support_custom_workflow_api_chain(
    monkeypatch: pytest.MonkeyPatch,
    route_client: TestClient,
) -> None:
    _clear_api_caches()
    store = WorkflowStore()
    definition = _sample_workflow_definition()

    async def _create_from_workflow(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            task_id="task-e2e-workflow-001",
            status=SimpleNamespace(value="pending"),
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    monkeypatch.setattr(
        app.state,
        "workflow_execution",
        SimpleNamespace(execute=_create_from_workflow),
        raising=False,
    )
    create_response = route_client.post(
        "/api/workflows",
        json={"name": "E2E Workflow", "definition": definition.model_dump()},
    )
    assert create_response.status_code == 201, create_response.text

    save_response = route_client.post(
        "/api/workflows/save",
        json={
            "name": "E2E Workflow Saved",
            "description": "support FE E2E",
            "definition": definition.model_dump(),
        },
    )
    assert save_response.status_code == 200
    workflow_id = save_response.json()["data"]["id"]

    get_response = route_client.get(f"/api/workflows/{workflow_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == workflow_id

    execute_response = route_client.post(
        f"/api/workflows/{workflow_id}/execute", json={"file_ids": []}
    )
    assert execute_response.status_code == 202
    execute_payload = execute_response.json()
    assert execute_payload["workflow_id"] == workflow_id
    assert execute_payload["task_id"] == "task-e2e-workflow-001"


def test_e2e_backend_support_multi_engine_compare_results_contract(
    monkeypatch: pytest.MonkeyPatch,
    route_client: TestClient,
    snapshot_repository: _SnapshotRepository,
) -> None:
    _clear_api_caches()
    now = datetime.now(timezone.utc)
    storage_root = Path("/tmp/docconv-e2e-compare")
    storage_root.mkdir(parents=True, exist_ok=True)
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_ocr", type="engine/ocr", config={}),
            WorkflowNode(id="engine_markitdown", type="engine/markitdown", config={}),
            WorkflowNode(id="output_md", type="output/markdown", config={}),
            WorkflowNode(id="output_txt", type="output/plaintext", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_ocr"),
            WorkflowConnection(source="input_1", target="engine_markitdown"),
            WorkflowConnection(source="engine_ocr", target="output_md"),
            WorkflowConnection(source="engine_markitdown", target="output_txt"),
        ],
    )
    md_result = _build_result(
        task_id="task-e2e-compare-001",
        storage_root=storage_root,
        result_id="res-md-001",
        output_format="markdown",
        content="# OCR Result",
    )
    txt_result = _build_result(
        task_id="task-e2e-compare-001",
        storage_root=storage_root,
        result_id="res-txt-001",
        output_format="plaintext",
        content="MarkItDown Result",
    )
    context = SimpleNamespace(
        task_id="task-e2e-compare-001",
        workflow=workflow,
        status=SimpleNamespace(value="completed"),
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=2048,
        engine="ocr",
        output_format="markdown",
        progress=TaskProgress(
            total_nodes=5,
            completed_nodes=5,
            failed_nodes=0,
            pending_nodes=0,
            skipped_nodes=0,
            percentage=100,
        ),
        node_states={
            "output_md": NodeState(
                node_id="output_md",
                node_type="output/markdown",
                status=NodeStatus.COMPLETED,
                output=md_result,
            ),
            "output_txt": NodeState(
                node_id="output_txt",
                node_type="output/plaintext",
                status=NodeStatus.COMPLETED,
                output=txt_result,
            ),
        },
        result=md_result,
        error=None,
    )
    snapshot_repository.snapshots[context.task_id] = TaskRunSnapshot(
        task_id=context.task_id,
        status="completed",
        workspace_id=TEST_WORKSPACE_ID,
        created_at=now,
        completed_at=now,
        updated_at=now,
        duration_ms=context.duration_ms,
        node_summary={"completed": 5},
        results=[
            {
                "result_id": md_result.result_id,
                "engine_type": "ocr",
                "output_format": "markdown",
                "result_preview": md_result.content,
                "duration_ms": md_result.metadata.processing_time_ms,
                "content": md_result.content,
            },
            {
                "result_id": txt_result.result_id,
                "engine_type": "markitdown",
                "output_format": "plaintext",
                "result_preview": txt_result.content,
                "duration_ms": txt_result.metadata.processing_time_ms,
                "content": txt_result.content,
            },
        ],
    )

    response = route_client.get(f"/api/tasks/{context.task_id}/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert len(payload["results"]) == 2
    by_engine = {item["engine_type"]: item for item in payload["results"]}
    assert by_engine["ocr"]["output_format"] == "markdown"
    assert by_engine["markitdown"]["output_format"] == "plaintext"
    for item in payload["results"]:
        assert {"engine_type", "output_format", "result_preview", "duration_ms"} <= set(item.keys())


def test_e2e_backend_support_errors_use_unified_error_contract(
    monkeypatch: pytest.MonkeyPatch,
    route_client: TestClient,
) -> None:
    _clear_api_caches()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: WorkflowStore())
    workflow_response = route_client.get("/api/workflows/wf-missing")
    task_response = route_client.get("/api/tasks/task-missing")
    invalid_workflow_response = route_client.post(
        "/api/workflows",
        json={
            "name": "invalid-workflow",
            "definition": {"nodes": [], "connections": []},
        },
    )

    assert workflow_response.status_code == 404
    workflow_payload = workflow_response.json()
    assert workflow_payload["error_code"] == "WORKFLOW_NOT_FOUND"
    assert isinstance(workflow_payload["trace_id"], str)
    assert "message" in workflow_payload

    assert task_response.status_code == 404
    task_payload = task_response.json()
    assert task_payload["error_code"] == "TASK_NOT_FOUND"
    assert isinstance(task_payload["trace_id"], str)

    assert invalid_workflow_response.status_code == 400
    invalid_payload = invalid_workflow_response.json()
    assert invalid_payload["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert isinstance(invalid_payload["trace_id"], str)
    assert isinstance(invalid_payload["details"].get("errors"), list)
