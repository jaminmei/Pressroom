"""Integration tests covering the doc-annotation runner UI contract.

These tests exercise the exact API call sequence the /doc-annotation frontend
page relies on:
  1. List test sets (GET /api/test-sets)
  2. Upload documents (POST /api/test-sets/{id}/documents/upload)
  3. List documents (GET /api/test-sets/{id}/documents)
  4. Download original file (GET /api/test-sets/{id}/documents/{doc_id}/file)
  5. Create evaluation run (POST /api/test-sets/{id}/evaluation-runs)
  6. Poll run status (GET /api/evaluation-runs/{run_id})
  7. Get run results (GET /api/evaluation-runs/{run_id}/results)
  8. Get result detail (GET /api/evaluation-runs/{run_id}/results/{result_id})
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
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

    db_path = tmp_path / "runner_contract.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    test_set_repository = TestSetRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    workflow_store = WorkflowStore()
    workflow = workflow_store.create(
        name="OCR Pipeline",
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
        _ = kwargs

    app.state.evaluation_service = SimpleNamespace(run_batch=_run_batch)
    app.state._test_engine = engine

    install_authenticated_workspace(app, monkeypatch)
    api_client = TestClient(app)
    try:
        yield api_client
    finally:
        remove_authenticated_workspace(app)
        asyncio.run(engine.dispose())


def test_runner_upload_and_download_contract(client: TestClient) -> None:
    """Upload a document to a test set and download it back — the runner happy path."""

    # 1. List test sets (initially empty)
    resp = client.get("/api/test-sets")
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # 2. Create a test set
    created = client.post("/api/test-sets", json={"name": "Invoices", "description": "E2E"})
    assert created.status_code == 201
    ts_id = created.json()["id"]

    # 3. List test sets again — contains the new one
    resp = client.get("/api/test-sets")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["id"] == ts_id

    # 4. Upload a document
    uploaded = client.post(
        f"/api/test-sets/{ts_id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake content", "application/pdf"))],
    )
    assert uploaded.status_code == 201
    upload_data = uploaded.json()
    assert len(upload_data["uploaded"]) == 1
    doc_id = upload_data["uploaded"][0]["id"]

    # 5. List documents
    docs_resp = client.get(f"/api/test-sets/{ts_id}/documents")
    assert docs_resp.status_code == 200
    docs = docs_resp.json()["items"]
    assert len(docs) == 1
    assert docs[0]["filename"] == "invoice.pdf"
    assert docs[0]["id"] == doc_id

    # 6. Download original file
    file_resp = client.get(f"/api/test-sets/{ts_id}/documents/{doc_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "application/pdf"
    assert file_resp.content == b"%PDF-1.4 fake content"


def test_runner_evaluation_run_lifecycle_contract(client: TestClient) -> None:
    """Create a test set, upload, create evaluation run, poll, and get results."""

    repository = client.app.state.test_set_repository
    evaluation_repository = client.app.state.evaluation_repository
    workflow = client.app.state.workflow

    # Setup: create test set and document
    test_set = asyncio.run(
        repository.create_test_set(
            name="Runner Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=5000,
            page_count=None,
            storage_path="test_sets/{}/documents/report.pdf".format(test_set.id),
        )
    )

    # 1. Create evaluation run — blocks concurrent duplicates
    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "OCR Run"},
    )
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "pending"
    assert run["total_documents"] == 1
    run_id = run["id"]

    # 2. Poll — still pending (background batch not executed in tests)
    poll = client.get(f"/api/evaluation-runs/{run_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending"

    # 3. Simulate batch completion via repository
    asyncio.run(
        evaluation_repository.update_run(
            run_id,
            status="completed",
            completed_count=1,
            failed_count=0,
            started_at=datetime(2026, 4, 29, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 29, 0, 0, 10, tzinfo=timezone.utc),
            duration_ms=10000,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    # The current run contract pre-creates one queued result per document.
    results = asyncio.run(
        evaluation_repository.list_results(
            run_id,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    assert len(results) == 1
    result = results[0]
    assert result.document_id == document.id
    assert result.status == "queued"
    asyncio.run(
        evaluation_repository.update_result(
            result.id,
            task_run_id="task_run_1",
            status="completed",
            output_content="# Report Output",
            output_format="markdown",
            processing_time_ms=500,
            error=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    # 4. Poll — now completed
    poll = client.get(f"/api/evaluation-runs/{run_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "completed"
    assert poll.json()["completed_count"] == 1

    # 5. Get results list
    results_resp = client.get(f"/api/evaluation-runs/{run_id}/results")
    assert results_resp.status_code == 200
    results_data = results_resp.json()
    assert results_data["summary"]["total"] == 1
    assert results_data["summary"]["completed"] == 1
    assert len(results_data["results"]) == 1
    assert results_data["results"][0]["filename"] == "report.pdf"
    # List view should NOT include output_content
    assert "output_content" not in results_data["results"][0]

    # 6. Get result detail — DOES include output_content
    detail_resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result.id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["output_content"] == "# Report Output"
    assert detail["output_format"] == "markdown"
    assert detail["filename"] == "report.pdf"
