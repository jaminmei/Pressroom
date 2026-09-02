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
            WorkflowNode(id="input_1", type="input", engine_id=None, config={}),
            WorkflowNode(id="engine_1", type="engine", engine_id="ocr_v1", config={}),
            WorkflowNode(id="output_1", type="output", engine_id=None, config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(evaluation_runs_router, prefix="/api")
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")

    db_path = tmp_path / "result_compare.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    test_set_repository = TestSetRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    ground_truth_repository = GroundTruthRepository(session_factory=session_factory)
    workflow_store = WorkflowStore()
    workflow = workflow_store.create(
        name="OCR Workflow",
        definition=_sample_definition(),
        workspace_id=TEST_WORKSPACE_ID,
    )

    app.state.test_set_repository = test_set_repository
    app.state.evaluation_repository = evaluation_repository
    app.state.ground_truth_repository = ground_truth_repository
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


def _create_completed_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    output_content: str = "# Extracted Text\n\nThis is the OCR output.",
) -> tuple[str, str, str]:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    evaluation_repo: EvaluationRepository = client.app.state.evaluation_repository  # type: ignore[union-attr]

    test_set = asyncio.run(
        repository.create_test_set(
            name="Compare Test Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    doc = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="sample.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/sample.pdf",
            size_bytes=1024,
            page_count=1,
        )
    )

    workflow_id = client.app.state.workflow.id  # type: ignore[union-attr]
    run_resp = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )
    run_id = run_resp.json()["id"]

    results_resp = client.get(f"/api/evaluation-runs/{run_id}/results")
    result_id = results_resp.json()["results"][0]["id"]

    asyncio.run(
        evaluation_repo.update_result(
            result_id,
            task_run_id=None,
            status="completed",
            output_content=output_content,
            output_format="markdown",
            processing_time_ms=1200,
            error=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    return run_id, result_id, doc.id


def _create_ground_truth(client: TestClient, document_id: str, content: str) -> str:
    gt_repo: GroundTruthRepository = client.app.state.ground_truth_repository  # type: ignore[union-attr]
    gt = asyncio.run(
        gt_repo.create_version(
            document_id=document_id,
            source="manual_upload",
            format="markdown",
            content=content,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    return gt.id


# --- Compare: matched ---


def test_compare_matched(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    content = "Hello world"
    run_id, result_id, doc_id = _create_completed_result(
        client, monkeypatch, output_content=content
    )
    _create_ground_truth(client, doc_id, content)

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_id"] == result_id
    assert body["document_id"] == doc_id
    assert body["comparison_status"] == "matched"
    assert body["diff_mode"] == "text"
    assert body["expected_content"] == content
    assert body["actual_content"] == content
    assert body["diff_fields"] == []


# --- Compare: matched with whitespace normalization ---


def test_compare_matched_with_whitespace_normalization(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(
        client, monkeypatch, output_content="Hello   world\n\n"
    )
    _create_ground_truth(client, doc_id, "Hello world")

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["comparison_status"] == "matched"
    assert body["diff_mode"] == "text"


# --- Compare: mismatched ---


def test_compare_mismatched(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, result_id, doc_id = _create_completed_result(
        client, monkeypatch, output_content="Actual output"
    )
    _create_ground_truth(client, doc_id, "Expected ground truth")

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["comparison_status"] == "mismatched"
    assert body["diff_mode"] == "text"
    assert body["expected_content"] == "Expected ground truth"
    assert body["actual_content"] == "Actual output"


# --- Compare: unavailable (no ground truth) ---


def test_compare_unavailable_no_ground_truth(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["comparison_status"] == "unavailable"
    assert body["diff_mode"] == "none"
    assert body["expected_content"] is None
    assert body["actual_content"] is not None


# --- Compare: not_compared (non-completed result) ---


def test_compare_not_compared_non_completed_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    test_set = asyncio.run(
        repository.create_test_set(
            name="Queued Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="queued.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/queued.pdf",
            size_bytes=512,
            page_count=1,
        )
    )

    workflow_id = client.app.state.workflow.id  # type: ignore[union-attr]
    run_resp = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )
    run_id = run_resp.json()["id"]
    results_resp = client.get(f"/api/evaluation-runs/{run_id}/results")
    result_id = results_resp.json()["results"][0]["id"]

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["comparison_status"] == "not_compared"
    assert body["diff_mode"] == "none"
    assert body["expected_content"] is None
    assert body["actual_content"] is None


# --- Compare: 404 ---


def test_compare_nonexistent_result_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    test_set = asyncio.run(
        repository.create_test_set(
            name="404 Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="doc.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc.pdf",
            size_bytes=512,
            page_count=1,
        )
    )
    workflow_id = client.app.state.workflow.id  # type: ignore[union-attr]
    run_resp = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )
    run_id = run_resp.json()["id"]

    resp = client.get(f"/api/evaluation-runs/{run_id}/results/nonexistent_id/compare")
    assert resp.status_code == 404


def test_compare_nonexistent_run_returns_404(client: TestClient) -> None:
    resp = client.get("/api/evaluation-runs/fake_run/results/fake_result/compare")
    assert resp.status_code == 404


# --- Results list includes comparison_status and review_status ---


def test_results_list_includes_comparison_and_review_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(client, monkeypatch)
    _create_ground_truth(client, doc_id, "# Extracted Text\n\nThis is the OCR output.")

    client.post(f"/api/evaluation-runs/{run_id}/results/{result_id}/comparison")

    resp = client.get(f"/api/evaluation-runs/{run_id}/results")
    assert resp.status_code == 200
    body = resp.json()
    result_row = body["results"][0]
    assert "comparison_status" in result_row
    assert "review_status" in result_row
    assert result_row["comparison_status"] == "matched"
    assert result_row["review_status"] == "unreviewed"


# --- Compare persists comparison_status on result ---


def test_comparison_refresh_persists_status_on_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(
        client, monkeypatch, output_content="different text"
    )
    _create_ground_truth(client, doc_id, "original text")

    client.post(f"/api/evaluation-runs/{run_id}/results/{result_id}/comparison")

    evaluation_repo: EvaluationRepository = client.app.state.evaluation_repository  # type: ignore[union-attr]
    result = asyncio.run(evaluation_repo.get_result(result_id, workspace_id=TEST_WORKSPACE_ID))
    assert result is not None
    assert result.comparison_status == "mismatched"


def test_comparison_get_is_pure_and_does_not_persist_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(
        client, monkeypatch, output_content="different text"
    )
    _create_ground_truth(client, doc_id, "original text")

    response = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}/comparison")
    assert response.status_code == 200
    assert response.json()["comparison_status"] == "mismatched"

    evaluation_repo: EvaluationRepository = client.app.state.evaluation_repository  # type: ignore[union-attr]
    result = asyncio.run(evaluation_repo.get_result(result_id, workspace_id=TEST_WORKSPACE_ID))
    assert result is not None
    assert result.comparison_status == "not_compared"
