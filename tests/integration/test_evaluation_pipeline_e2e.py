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
from app.api.ground_truths import router as ground_truths_router
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

TEST_PDF_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "stress" / "single-page.pdf"


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
    app.include_router(ground_truths_router, prefix="/api")
    app.include_router(evaluation_runs_router, prefix="/api")
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")

    db_path = tmp_path / "evaluation_pipeline_e2e.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    test_set_repository = TestSetRepository(session_factory=session_factory)
    ground_truth_repository = GroundTruthRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    workflow_store = WorkflowStore()
    workflow = workflow_store.create(
        name="Eval Pipeline",
        definition=_sample_definition(),
        workspace_id=TEST_WORKSPACE_ID,
    )

    app.state.test_set_repository = test_set_repository
    app.state.ground_truth_repository = ground_truth_repository
    app.state.evaluation_repository = evaluation_repository
    app.state.workflow_store = workflow_store
    app.state.workflow = workflow
    app.state.test_set_storage = TestSetStorage(tmp_path / "storage")

    async def _run_batch(**kwargs: object) -> None:
        run_id: str = kwargs["run_id"]
        kwargs["test_set_id"]
        kwargs["workflow"]
        pre_created = await evaluation_repository.list_results(
            str(run_id), workspace_id=TEST_WORKSPACE_ID
        )
        if pre_created:
            result = pre_created[0]
            await evaluation_repository.update_result(
                result.id,
                task_run_id=f"task_{run_id}",
                status="completed",
                output_content="# Mock OCR Output",
                output_format="markdown",
                processing_time_ms=42,
                error=None,
                workspace_id=TEST_WORKSPACE_ID,
            )
        await evaluation_repository.update_run(
            str(run_id),
            status="completed",
            completed_count=len(pre_created),
            failed_count=0,
            duration_ms=42,
            workspace_id=TEST_WORKSPACE_ID,
        )

    async def _apply_result_as_ground_truth(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            id="gt_apply_1",
            document_id=kwargs["document_id"],
            version=2,
            source="inference_apply",
            format="markdown",
            content="# Mock Output",
            source_task_run_id=kwargs["task_run_id"],
            notes=kwargs["notes"],
            created_at=None,
        )

    app.state.evaluation_service = SimpleNamespace(
        run_batch=_run_batch,
        apply_result_as_ground_truth=_apply_result_as_ground_truth,
    )
    app.state._test_engine = engine

    install_authenticated_workspace(app, monkeypatch)
    api_client = TestClient(app)
    try:
        yield api_client
    finally:
        remove_authenticated_workspace(app)
        asyncio.run(engine.dispose())


def test_evaluation_pipeline_e2e(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_PDF_PATH.exists(), f"Test PDF not found at {TEST_PDF_PATH}"

    repository: TestSetRepository = client.app.state.test_set_repository
    evaluation_repository: EvaluationRepository = client.app.state.evaluation_repository
    workflow = client.app.state.workflow

    captured_coros: list[object] = []

    def _capture_and_discard(coro: object) -> object:
        captured_coros.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _capture_and_discard)

    test_set = asyncio.run(
        repository.create_test_set(
            name="Pipeline E2E Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    with open(TEST_PDF_PATH, "rb") as fh:
        pdf_bytes = fh.read()

    uploaded = client.post(
        f"/api/test-sets/{test_set.id}/documents/upload",
        files=[("files", ("single-page.pdf", pdf_bytes, "application/pdf"))],
    )
    assert uploaded.status_code == 201
    upload_payload = uploaded.json()
    assert upload_payload["errors"] == []
    assert len(upload_payload["uploaded"]) == 1
    upload_payload["uploaded"][0]["id"]

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Pipeline E2E Run"},
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["status"] == "pending"
    run_id = created_payload["id"]

    initial_results = asyncio.run(
        evaluation_repository.list_results(run_id, workspace_id=TEST_WORKSPACE_ID)
    )
    assert len(initial_results) == 1
    assert initial_results[0].status == "queued"

    asyncio.run(
        evaluation_repository.update_result(
            initial_results[0].id,
            task_run_id=f"task_{run_id}",
            status="completed",
            output_content="# E2E Pipeline Output",
            output_format="markdown",
            processing_time_ms=123,
            error=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        evaluation_repository.update_run(
            run_id,
            status="completed",
            completed_count=1,
            failed_count=0,
            duration_ms=123,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    detail = client.get(f"/api/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"

    results = client.get(f"/api/evaluation-runs/{run_id}/results")
    assert results.status_code == 200
    results_payload = results.json()
    assert results_payload["summary"]["total"] >= 1, "Expected at least one evaluation result"
    result_id = results_payload["results"][0]["id"]

    result_detail = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}")
    assert result_detail.status_code == 200
    detail_payload = result_detail.json()
    assert detail_payload["task_run_id"] is not None, (
        f"Expected task_run_id to be populated, got {detail_payload['task_run_id']}"
    )
    assert detail_payload["filename"] == "single-page.pdf"
    assert detail_payload["status"] == "completed"
