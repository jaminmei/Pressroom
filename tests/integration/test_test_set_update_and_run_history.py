from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.evaluation_runs import router as evaluation_runs_router
from app.api.test_documents import router as test_documents_router
from app.api.test_sets import router as test_sets_router
from app.db.base import Base
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.workflow_store import WorkflowStore
from app.storage.test_set_storage import TestSetStorage
from tests._api_workspace_contract import (
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


def _sample_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/document", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="output/markdown", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")
    app.include_router(evaluation_runs_router, prefix="/api")

    db_path = tmp_path / "test_set_update_run_history.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    test_set_repository = TestSetRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    workflow_store = WorkflowStore()
    workflow = workflow_store.create(
        name="OCR Workflow",
        definition=_sample_definition(),
        workspace_id=TEST_WORKSPACE_ID,
    )

    app.state.test_set_repository = test_set_repository
    app.state.evaluation_repository = evaluation_repository
    app.state.ground_truth_repository = GroundTruthRepository(session_factory=session_factory)
    app.state.workflow_store = workflow_store
    app.state.workflow = workflow
    app.state.test_set_storage = TestSetStorage(tmp_path / "storage")

    async def _run_batch(**kwargs: object) -> None:
        pass

    app.state.evaluation_service = SimpleNamespace(run_batch=_run_batch)

    install_authenticated_workspace(app, monkeypatch)
    api_client = TestClient(app)
    try:
        yield api_client
    finally:
        remove_authenticated_workspace(app)
        asyncio.run(engine.dispose())


def _stub_background(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    scheduled: list[object] = []

    def _fake_create_task(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _fake_create_task)
    return scheduled


# --- PATCH /api/test-sets/{id} ---


def test_patch_update_name_only(client: TestClient) -> None:
    created = client.post(
        "/api/test-sets", json={"name": "Original", "description": "Original desc"}
    ).json()
    ts_id = created["id"]

    resp = client.patch(f"/api/test-sets/{ts_id}", json={"name": "Updated"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Updated"
    assert body["description"] == "Original desc"


def test_patch_update_name_and_description(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Old", "description": "Old desc"}).json()
    ts_id = created["id"]

    resp = client.patch(f"/api/test-sets/{ts_id}", json={"name": "New", "description": "New desc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New"
    assert body["description"] == "New desc"


def test_patch_empty_name_rejected(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Valid"}).json()
    ts_id = created["id"]

    resp = client.patch(f"/api/test-sets/{ts_id}", json={"name": ""})
    assert resp.status_code == 422


def test_patch_nonexistent_test_set(client: TestClient) -> None:
    resp = client.patch("/api/test-sets/ts_nonexistent", json={"name": "X"})
    assert resp.status_code == 404


def test_patch_empty_body_returns_unchanged(client: TestClient) -> None:
    created = client.post(
        "/api/test-sets", json={"name": "Unchanged", "description": "Keep"}
    ).json()
    ts_id = created["id"]

    resp = client.patch(f"/api/test-sets/{ts_id}", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Unchanged"
    assert body["description"] == "Keep"


def test_patch_set_description_to_null(client: TestClient) -> None:
    created = client.post(
        "/api/test-sets", json={"name": "HasDesc", "description": "Will remove"}
    ).json()
    ts_id = created["id"]

    resp = client.patch(f"/api/test-sets/{ts_id}", json={"description": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "HasDesc"
    assert body["description"] is None


# --- GET /api/test-sets/{id}/evaluation-runs ---


def test_run_history_returns_runs_ordered_desc(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    created = client.post("/api/test-sets", json={"name": "HistorySet"}).json()
    ts_id = created["id"]
    workflow_id = client.app.state.workflow.id

    repository = client.app.state.test_set_repository
    asyncio.run(
        repository.create_test_document(
            test_set_id=ts_id,
            filename="a.pdf",
            mime_type="application/pdf",
            storage_path="/tmp/a.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    client.post(
        f"/api/test-sets/{ts_id}/evaluation-runs",
        json={"workflow_id": workflow_id, "name": "Run 1", "client_request_id": "r1"},
    )

    eval_repo = client.app.state.evaluation_repository
    runs = asyncio.run(eval_repo.list_runs_for_test_set(ts_id, workspace_id=TEST_WORKSPACE_ID))
    asyncio.run(
        eval_repo.update_run(
            runs[0].id,
            status="completed",
            completed_count=1,
            failed_count=0,
            duration_ms=500,
            started_at=runs[0].created_at,
            completed_at=runs[0].created_at,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    client.post(
        f"/api/test-sets/{ts_id}/evaluation-runs",
        json={"workflow_id": workflow_id, "name": "Run 2", "client_request_id": "r2"},
    )

    resp = client.get(f"/api/test-sets/{ts_id}/evaluation-runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["items"][0]["name"] == "Run 2"
    assert body["items"][1]["name"] == "Run 1"


def test_run_history_includes_result_and_review_summary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    created = client.post("/api/test-sets", json={"name": "SummarySet"}).json()
    ts_id = created["id"]
    workflow_id = client.app.state.workflow.id

    repository = client.app.state.test_set_repository
    asyncio.run(
        repository.create_test_document(
            test_set_id=ts_id,
            filename="b.pdf",
            mime_type="application/pdf",
            storage_path="/tmp/b.pdf",
            size_bytes=200,
            page_count=2,
        )
    )

    client.post(
        f"/api/test-sets/{ts_id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )

    resp = client.get(f"/api/test-sets/{ts_id}/evaluation-runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]

    assert "result_summary" in item
    rs = item["result_summary"]
    assert rs["total"] == 1
    assert rs["queued"] == 1
    assert rs["completed"] == 0
    assert rs["failed"] == 0
    assert rs["running"] == 0

    assert "review_summary" in item
    rv = item["review_summary"]
    assert rv["unreviewed"] == 1
    assert rv["accepted"] == 0
    assert rv["rejected"] == 0


def test_run_history_includes_workflow_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    created = client.post("/api/test-sets", json={"name": "WfNameSet"}).json()
    ts_id = created["id"]
    workflow_id = client.app.state.workflow.id

    repository = client.app.state.test_set_repository
    asyncio.run(
        repository.create_test_document(
            test_set_id=ts_id,
            filename="c.pdf",
            mime_type="application/pdf",
            storage_path="/tmp/c.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    client.post(
        f"/api/test-sets/{ts_id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )

    resp = client.get(f"/api/test-sets/{ts_id}/evaluation-runs")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["workflow_name"] == "OCR Workflow"


def test_run_history_404_nonexistent_test_set(client: TestClient) -> None:
    resp = client.get("/api/test-sets/ts_nonexistent/evaluation-runs")
    assert resp.status_code == 404
