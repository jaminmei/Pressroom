from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import tasks as tasks_api
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


def _build_result(
    *,
    result_id: str,
    output_format: str,
    content: str,
) -> TaskResult:
    extension = {"markdown": "md", "plaintext": "txt"}.get(output_format, "txt")
    media_type = {"markdown": "text/markdown", "plaintext": "text/plain"}.get(
        output_format, "text/plain"
    )
    return TaskResult(
        result_id=result_id,
        format=output_format,
        filename=f"{result_id}.{extension}",
        content_type=media_type,
        storage_path=f"/tmp/{result_id}.{extension}",
        download_url=f"/api/tasks/task-step13/results/{result_id}/download",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=180,
            page_count=1,
            char_count=len(content),
            word_count=max(len(content.split()), 1),
            source_filename="sample.txt",
        ),
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
    monkeypatch.setattr(tasks_api, "_start_dag_run", lambda **_kwargs: None)
    client = TestClient(app)
    yield client
    client.close()


def test_tc_be_s3_rg_01_tasks_api_serial_flow_regression(
    route_client: TestClient,
    snapshot_repository: _SnapshotRepository,
) -> None:
    now = datetime.now(timezone.utc)
    create_resp = route_client.post(
        "/api/tasks",
        data={"engine": "text", "output_format": "markdown"},
        files={"file": ("input.txt", b"hello world", "text/plain")},
    )
    assert create_resp.status_code == 202
    task_id = create_resp.json()["task_id"]
    assert task_id.startswith("task_")
    snapshot_repository.snapshots[task_id] = TaskRunSnapshot(
        task_id=task_id,
        status="completed",
        workspace_id=TEST_WORKSPACE_ID,
        created_at=now,
        completed_at=now,
        updated_at=now,
        node_summary={"completed": 1},
    )

    status_resp = route_client.get(f"/api/tasks/{task_id}")
    assert status_resp.status_code == 200
    status_payload = status_resp.json()
    assert status_payload["status"] == "completed"
    assert status_payload["progress"]["completed_nodes"] == 1


def test_tc_be_s3_rg_02_workflow_crud_publish_restore_regression(
    monkeypatch: pytest.MonkeyPatch,
    route_client: TestClient,
) -> None:
    store = WorkflowStore()
    definition = _sample_workflow_definition()

    async def _create_from_workflow(*_args, **_kwargs):
        return SimpleNamespace(
            task_id="task-rg-workflow-001",
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
    create_resp = route_client.post(
        "/api/workflows/save",
        json={
            "name": "step13-rg",
            "description": "baseline",
            "definition": definition.model_dump(),
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    workflow_id = created["id"]

    get_resp = route_client.get(f"/api/workflows/{workflow_id}")
    assert get_resp.status_code == 200

    update_resp = route_client.post(
        "/api/workflows/save",
        json={
            "workflow_id": workflow_id,
            "workflow_key": created["workflow_key"],
            "base_version": created["latest_version"],
            "name": "step13-rg-updated",
            "definition": definition.model_dump(),
        },
    )
    assert update_resp.status_code == 200

    publish_resp = route_client.post(f"/api/workflows/{workflow_id}/publish")
    assert publish_resp.status_code == 200
    assert publish_resp.json()["data"]["version"] == 2

    restore_resp = route_client.post(f"/api/workflows/{workflow_id}/restore", json={"version": 1})
    assert restore_resp.status_code == 200
    assert restore_resp.json()["data"]["restored_version"] == 1

    execute_resp = route_client.post(
        f"/api/workflows/{workflow_id}/execute",
        json={"file_ids": []},
    )
    assert execute_resp.status_code == 202
    assert execute_resp.json()["task_id"] == "task-rg-workflow-001"


def test_tc_be_s3_e2e_01_results_api_supports_compare_panel_fields(
    route_client: TestClient,
    snapshot_repository: _SnapshotRepository,
) -> None:
    now = datetime.now(timezone.utc)
    workflow = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_ocr", type="engine/ocr", config={}),
            WorkflowNode(id="engine_vlm", type="engine/model", config={}),
            WorkflowNode(id="output_md", type="output/markdown", config={}),
            WorkflowNode(id="output_txt", type="output/plaintext", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_ocr"),
            WorkflowConnection(source="input_1", target="engine_vlm"),
            WorkflowConnection(source="engine_ocr", target="output_md"),
            WorkflowConnection(source="engine_vlm", target="output_txt"),
        ],
    )
    md_result = _build_result(result_id="res-md", output_format="markdown", content="# OCR Result")
    txt_result = _build_result(result_id="res-txt", output_format="plaintext", content="VLM Result")
    context = SimpleNamespace(
        task_id="task-e2e-results-001",
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
                "engine_type": "vlm",
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
    assert by_engine["vlm"]["output_format"] == "plaintext"
    for item in payload["results"]:
        assert {"engine_type", "output_format", "result_preview", "duration_ms"} <= set(item.keys())


def test_tc_be_s3_e2e_03_history_returns_result_preview_for_recent_runs(
    route_client: TestClient,
    snapshot_repository: _SnapshotRepository,
) -> None:
    now = datetime.now(timezone.utc)
    snapshot_repository.snapshots["task-e2e-history-001"] = TaskRunSnapshot(
        task_id="task-e2e-history-001",
        status="completed",
        workspace_id=TEST_WORKSPACE_ID,
        workflow_id="wf-step13-history",
        workflow_name="Step13 History Workflow",
        created_at=now,
        completed_at=now,
        duration_ms=3210,
        node_summary={"total": 3, "completed": 3, "failed": 0},
        result_preview="preview from persisted snapshot",
    )
    response = route_client.get("/api/tasks/history?page=1&limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["meta"]["total"] == 1
    assert payload["data"][0]["result_preview"] == "preview from persisted snapshot"
