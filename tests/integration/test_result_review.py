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
    app.include_router(evaluation_runs_router, prefix="/api")
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")

    db_path = tmp_path / "result_review.sqlite3"
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
) -> tuple[str, str, str]:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    evaluation_repo: EvaluationRepository = client.app.state.evaluation_repository  # type: ignore[union-attr]

    test_set = asyncio.run(
        repository.create_test_set(
            name="Review Test Set",
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
            output_content="# Extracted Text\n\nThis is the OCR output.",
            output_format="markdown",
            processing_time_ms=1200,
            error=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    return run_id, result_id, doc.id


# --- Accept ---


def test_accept_creates_ground_truth_and_updates_review(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
        json={"notes": "Looks correct"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "accepted"
    assert body["accepted_ground_truth_id"] is not None
    assert body["review_notes"] == "Looks correct"
    assert body["reviewed_at"] is not None
    assert body["comparison_status"] == "matched"


def test_accept_without_body(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "accepted"
    assert body["accepted_ground_truth_id"] is not None
    assert body["review_notes"] is None


def test_accept_creates_gt_with_result_output(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(client, monkeypatch)

    client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
    )

    gt_repo: GroundTruthRepository = client.app.state.ground_truth_repository  # type: ignore[union-attr]
    gt = asyncio.run(gt_repo.get_latest(doc_id, workspace_id=TEST_WORKSPACE_ID))
    assert gt is not None
    assert gt.source == "review_accept"
    assert gt.format == "markdown"
    assert gt.content == "# Extracted Text\n\nThis is the OCR output."


# --- Reject ---


def test_reject_updates_review_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/reject",
        json={"reason": "Output is garbled"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "rejected"
    assert body["accepted_ground_truth_id"] is None
    assert body["review_notes"] == "Output is garbled"
    assert body["reviewed_at"] is not None


def test_reject_does_not_create_ground_truth(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, result_id, doc_id = _create_completed_result(client, monkeypatch)

    client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/reject",
        json={"reason": "Bad"},
    )

    gt_repo: GroundTruthRepository = client.app.state.ground_truth_repository  # type: ignore[union-attr]
    gt = asyncio.run(gt_repo.get_latest(doc_id, workspace_id=TEST_WORKSPACE_ID))
    assert gt is None


# --- Re-review ---


def test_re_accept_after_reject(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/reject",
        json={"reason": "Initially bad"},
    )

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
        json={"notes": "Actually looks good after review"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "accepted"
    assert body["accepted_ground_truth_id"] is not None
    assert body["review_notes"] == "Actually looks good after review"
    assert body["comparison_status"] == "matched"


def test_re_reject_after_accept(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, result_id, _doc_id = _create_completed_result(client, monkeypatch)

    client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
        json={"notes": "OK"},
    )

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/reject",
        json={"reason": "Changed my mind"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "rejected"
    assert body["accepted_ground_truth_id"] is None
    assert body["review_notes"] == "Changed my mind"


# --- Validation edge cases ---


def test_accept_non_completed_result_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    test_set = asyncio.run(
        repository.create_test_set(
            name="Validation Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="a.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/a.pdf",
            size_bytes=100,
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

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
    )
    assert resp.status_code == 422
    assert "completed" in resp.json()["detail"].lower()


def test_reject_non_completed_result_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)

    repository: TestSetRepository = client.app.state.test_set_repository  # type: ignore[union-attr]
    test_set = asyncio.run(
        repository.create_test_set(
            name="Validation Set 2",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="b.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/b.pdf",
            size_bytes=100,
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

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/{result_id}/reject",
        json={"reason": "bad"},
    )
    assert resp.status_code == 422


def test_accept_nonexistent_result_returns_404(
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
            filename="c.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/c.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    workflow_id = client.app.state.workflow.id  # type: ignore[union-attr]
    run_resp = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow_id},
    )
    run_id = run_resp.json()["id"]

    resp = client.post(
        f"/api/evaluation-runs/{run_id}/results/nonexistent-id/accept-as-ground-truth",
    )
    assert resp.status_code == 404


def test_accept_nonexistent_run_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/api/evaluation-runs/fake-run/results/fake-result/accept-as-ground-truth",
    )
    assert resp.status_code == 404
