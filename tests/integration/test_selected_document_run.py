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

    db_path = tmp_path / "selected_doc_run.sqlite3"
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
        name="Test Workflow",
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


def _create_test_set_with_docs(
    client: TestClient, *, name: str, doc_count: int
) -> tuple[object, list[object]]:
    repository = client.app.state.test_set_repository
    test_set = asyncio.run(
        repository.create_test_set(
            name=name,
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    docs = []
    for i in range(doc_count):
        doc = asyncio.run(
            repository.create_test_document(
                test_set_id=test_set.id,
                filename=f"doc_{i}.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_{i}.pdf",
                size_bytes=100 + i,
                page_count=1,
            )
        )
        docs.append(doc)
    return test_set, docs


def test_create_run_with_selected_documents(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, docs = _create_test_set_with_docs(client, name="Select Set", doc_count=3)

    selected = [docs[0].id, docs[2].id]
    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Selected", "document_ids": selected},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["total_documents"] == 2

    results = client.get(f"/api/evaluation-runs/{payload['id']}/results")
    assert results.status_code == 200
    results_body = results.json()
    assert results_body["summary"]["total"] == 2
    result_doc_ids = {r["document_id"] for r in results_body["results"]}
    assert result_doc_ids == set(selected)
    assert all(r["status"] == "queued" for r in results_body["results"])


def test_create_run_without_document_ids_defaults_to_all(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, docs = _create_test_set_with_docs(client, name="All Set", doc_count=3)

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "All Docs"},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["total_documents"] == 3

    results = client.get(f"/api/evaluation-runs/{payload['id']}/results")
    assert results.status_code == 200
    results_body = results.json()
    assert results_body["summary"]["total"] == 3
    result_doc_ids = {r["document_id"] for r in results_body["results"]}
    assert result_doc_ids == {d.id for d in docs}
    assert all(r["status"] == "queued" for r in results_body["results"])


def test_create_run_rejects_invalid_document_ids(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, _docs = _create_test_set_with_docs(client, name="Invalid Set", doc_count=1)

    response = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Bad IDs",
            "document_ids": ["nonexistent_doc_id"],
        },
    )

    assert response.status_code == 422
    assert "nonexistent_doc_id" in response.json()["detail"]

    evaluation_repo = client.app.state.evaluation_repository
    runs = asyncio.run(
        evaluation_repo.list_runs_for_test_set(test_set.id, workspace_id=TEST_WORKSPACE_ID)
    )
    assert len(runs) == 0


def test_create_run_rejects_mixed_valid_invalid_document_ids(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, docs = _create_test_set_with_docs(client, name="Mixed Set", doc_count=2)

    response = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Mixed IDs",
            "document_ids": [docs[0].id, "nonexistent_id"],
        },
    )

    assert response.status_code == 422
    assert "nonexistent_id" in response.json()["detail"]

    evaluation_repo = client.app.state.evaluation_repository
    runs = asyncio.run(
        evaluation_repo.list_runs_for_test_set(test_set.id, workspace_id=TEST_WORKSPACE_ID)
    )
    assert len(runs) == 0


def test_idempotency_returns_existing_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, _docs = _create_test_set_with_docs(client, name="Idempotent Set", doc_count=1)

    first = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "First",
            "client_request_id": "abc-123",
        },
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Duplicate",
            "client_request_id": "abc-123",
        },
    )
    assert second.status_code == 200
    assert second.json()["id"] == first_id


def test_idempotency_with_different_key_creates_new_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    evaluation_repo = client.app.state.evaluation_repository
    test_set, _docs = _create_test_set_with_docs(client, name="Diff Key Set", doc_count=1)

    first = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Key 1",
            "client_request_id": "key-1",
        },
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    asyncio.run(
        evaluation_repo.update_run(
            first_id,
            status="completed",
            completed_count=1,
            failed_count=0,
            duration_ms=100,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    second = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Key 2",
            "client_request_id": "key-2",
        },
    )
    assert second.status_code == 201
    assert second.json()["id"] != first_id


def test_pre_created_results_have_queued_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, docs = _create_test_set_with_docs(client, name="Queued Set", doc_count=2)

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={
            "workflow_id": workflow.id,
            "name": "Queued Run",
            "document_ids": [docs[0].id, docs[1].id],
        },
    )
    assert created.status_code == 201

    results = client.get(f"/api/evaluation-runs/{created.json()['id']}/results")
    assert results.status_code == 200
    results_body = results.json()
    assert len(results_body["results"]) == 2
    for r in results_body["results"]:
        assert r["status"] == "queued"
        assert r["document_id"] in {docs[0].id, docs[1].id}


def test_create_run_with_empty_document_ids_defaults_to_all(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_background(monkeypatch)
    workflow = client.app.state.workflow
    test_set, docs = _create_test_set_with_docs(client, name="Empty IDs Set", doc_count=2)

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Empty IDs", "document_ids": []},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["total_documents"] == 2

    results = client.get(f"/api/evaluation-runs/{payload['id']}/results")
    assert results.status_code == 200
    results_body = results.json()
    assert results_body["summary"]["total"] == 2
    result_doc_ids = {r["document_id"] for r in results_body["results"]}
    assert result_doc_ids == {d.id for d in docs}
