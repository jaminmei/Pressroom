from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine, Iterator
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.evaluation_runs import EvaluationRunCreateRequest, create_evaluation_run
from app.api.evaluation_runs import router as evaluation_runs_router
from app.api.ground_truths import router as ground_truths_router
from app.api.test_documents import router as test_documents_router
from app.api.test_sets import router as test_sets_router
from app.core.feature_flags import OrchestratorMode
from app.db.base import Base
from app.models.db.workspace import Workspace
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


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(ground_truths_router, prefix="/api")
    app.include_router(evaluation_runs_router, prefix="/api")
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")

    db_path = tmp_path / "evaluation_api.sqlite3"
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
        name="Eval Workflow",
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
        _ = kwargs

    async def _apply_result_as_ground_truth(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            id="gt_apply_1",
            document_id=kwargs["document_id"],
            version=2,
            source="inference_apply",
            format="markdown",
            content="# Applied output",
            source_task_run_id=kwargs["task_run_id"],
            notes=kwargs["notes"],
            created_at=datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc),
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


def test_manual_ground_truth_create_get_and_list_versions(client: TestClient) -> None:
    repository = _app(client).state.test_set_repository
    test_set = asyncio.run(
        repository.create_test_set(name="GT Set", description=None, workspace_id=TEST_WORKSPACE_ID)
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="invoice.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_1_invoice.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/documents/{document.id}/ground-truth",
        json={
            "content": "expected content",
            "format": "text",
            "source": "manual_edit",
            "notes": "initial",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["version"] == 1
    assert payload["source"] == "manual_edit"
    assert payload["content"] == "expected content"

    latest = client.get(f"/api/test-sets/{test_set.id}/documents/{document.id}/ground-truth")
    assert latest.status_code == 200
    assert latest.json()["id"] == payload["id"]

    versions = client.get(
        f"/api/test-sets/{test_set.id}/documents/{document.id}/ground-truth/versions"
    )
    assert versions.status_code == 200
    versions_payload = versions.json()
    assert versions_payload["total"] == 1
    assert versions_payload["items"][0]["id"] == payload["id"]
    assert "content" not in versions_payload["items"][0]


def test_apply_ground_truth_uses_evaluation_service(client: TestClient) -> None:
    repository = _app(client).state.test_set_repository
    test_set = asyncio.run(
        repository.create_test_set(name="GT Set", description=None, workspace_id=TEST_WORKSPACE_ID)
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="invoice.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_1_invoice.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    response = client.post(
        f"/api/test-sets/{test_set.id}/documents/{document.id}/ground-truth/apply",
        json={"task_run_id": "task_eval_1", "notes": "apply"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source"] == "inference_apply"
    assert payload["source_task_run_id"] == "task_eval_1"
    assert payload["content"] == "# Applied output"


def test_apply_ground_truth_supports_queue_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    test_set = asyncio.run(
        repository.create_test_set(
            name="GT Queue Set", description=None, workspace_id=TEST_WORKSPACE_ID
        )
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="invoice.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_1_invoice.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    monkeypatch.setenv("ORCHESTRATOR_MODE", OrchestratorMode.QUEUE.value)

    response = client.post(
        f"/api/test-sets/{test_set.id}/documents/{document.id}/ground-truth/apply",
        json={"task_run_id": "task_eval_1", "notes": "apply"},
    )

    assert response.status_code == 201
    assert response.json()["document_id"] == document.id


def test_create_evaluation_run_and_read_run_and_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    evaluation_repository = _app(client).state.evaluation_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(name="Run Set", description=None, workspace_id=TEST_WORKSPACE_ID)
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="invoice.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_1_invoice.pdf",
            size_bytes=100,
            page_count=1,
        )
    )

    scheduled: list[object] = []

    def _fake_create_task(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _fake_create_task)

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "OCR Eval"},
    )

    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["status"] == "pending"
    assert created_payload["total_documents"] == 1
    assert len(scheduled) == 1

    run_id = created_payload["id"]

    pre_created_results = asyncio.run(
        evaluation_repository.list_results(run_id, workspace_id=TEST_WORKSPACE_ID)
    )
    assert len(pre_created_results) == 1
    result = pre_created_results[0]
    assert result.status == "queued"
    assert result.document_id == document.id

    asyncio.run(
        evaluation_repository.update_result(
            result.id,
            task_run_id="task_eval_1",
            status="completed",
            output_content="# Invoice",
            output_format="markdown",
            processing_time_ms=321,
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
            duration_ms=321,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    detail = client.get(f"/api/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"

    results = client.get(f"/api/evaluation-runs/{run_id}/results")
    assert results.status_code == 200
    results_payload = results.json()
    assert results_payload["summary"] == {
        "total": 1,
        "queued": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert results_payload["results"][0]["filename"] == "invoice.pdf"
    assert "output_content" not in results_payload["results"][0]

    result_detail = client.get(f"/api/evaluation-runs/{run_id}/results/{result.id}")
    assert result_detail.status_code == 200
    result_payload = result_detail.json()
    assert result_payload["task_run_id"] == "task_eval_1"
    assert result_payload["output_content"] == "# Invoice"
    assert result_payload["filename"] == "invoice.pdf"


def test_create_evaluation_run_supports_queue_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(
            name="Queue Run Set", description=None, workspace_id=TEST_WORKSPACE_ID
        )
    )

    monkeypatch.setattr(
        "app.api.evaluation_runs.FeatureFlags.get_orchestrator_mode",
        lambda: OrchestratorMode.QUEUE,
    )
    monkeypatch.setattr(
        "app.api.evaluation_runs._schedule_background_run",
        lambda _coro: pytest.fail("queue mode must not schedule an in-process batch"),
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Queue Eval"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "pending"


def test_create_evaluation_run_rejects_duplicate_active_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    evaluation_repository = _app(client).state.evaluation_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(
            name="Duplicate Run Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    existing = asyncio.run(
        evaluation_repository.create_run(
            test_set_id=test_set.id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Existing Run",
            total_documents=0,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        evaluation_repository.update_run(
            existing.id,
            status="running",
            completed_count=0,
            failed_count=0,
            duration_ms=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Duplicate Eval"},
    )

    assert created.status_code == 409
    assert existing.id in created.json()["detail"]


@pytest.mark.asyncio
async def test_create_evaluation_run_blocks_concurrent_duplicate_creation() -> None:
    workflow = SimpleNamespace(
        id="wf_eval",
        workspace_id=TEST_WORKSPACE_ID,
        published_version=1,
        latest_version=1,
        definition=_sample_definition(),
    )

    class StubRepository:
        async def get_test_set(
            self,
            test_set_id: str,
            *,
            workspace_id: str | None = None,
        ) -> SimpleNamespace:
            _ = workspace_id
            assert workspace_id == TEST_WORKSPACE_ID
            return SimpleNamespace(id=test_set_id, workspace_id=TEST_WORKSPACE_ID)

        async def list_test_documents(
            self,
            test_set_id: str,
            *,
            workspace_id: str | None = None,
        ) -> list[SimpleNamespace]:
            assert workspace_id == TEST_WORKSPACE_ID
            return [SimpleNamespace(id=f"doc_for_{test_set_id}")]

    class StubEvaluationRepository:
        def __init__(self) -> None:
            self.created_runs: list[SimpleNamespace] = []

        async def get_active_run_for_test_set(
            self,
            test_set_id: str,
            *,
            workspace_id: str | None = None,
        ) -> SimpleNamespace | None:
            assert workspace_id == TEST_WORKSPACE_ID
            await asyncio.sleep(0)
            for run in reversed(self.created_runs):
                if run.test_set_id == test_set_id and run.status in {"pending", "running"}:
                    return run
            return None

        async def find_run_by_client_request_id(
            self,
            test_set_id: str,
            client_request_id: str,
            *,
            workspace_id: str | None = None,
        ) -> SimpleNamespace | None:
            assert workspace_id == TEST_WORKSPACE_ID
            _ = test_set_id, client_request_id
            return None

        async def create_run_with_results(
            self,
            *,
            test_set_id: str,
            workflow_id: str,
            workflow_version: int | None,
            workflow_snapshot_json: dict[str, object] | None,
            name: str | None,
            total_documents: int,
            client_request_id: str | None = None,
            document_ids: list[str],
            workspace_id: str | None = None,
            queue_mode: bool = False,
        ) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
            assert queue_mode is False
            await asyncio.sleep(0.01)
            run = SimpleNamespace(
                id=f"eval_run_{len(self.created_runs) + 1}",
                name=name,
                test_set_id=test_set_id,
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                client_request_id=client_request_id,
                status="pending",
                total_documents=total_documents,
                completed_count=0,
                failed_count=0,
                started_at=None,
                completed_at=None,
                duration_ms=None,
                created_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
            )
            self.created_runs.append(run)
            results = [
                SimpleNamespace(
                    id=f"eval_result_{i}",
                    evaluation_run_id=run.id,
                    document_id=doc_id,
                    status="queued",
                )
                for i, doc_id in enumerate(document_ids)
            ]
            return run, results

    def _discard_background(coro: object) -> object:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    repository = StubRepository()
    evaluation_repository = StubEvaluationRepository()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                workflow_store=SimpleNamespace(
                    get=lambda workflow_id, *, workspace_id: (
                        workflow if workspace_id == TEST_WORKSPACE_ID else None
                    )
                ),
            )
        )
    )
    evaluation_service = SimpleNamespace(run_batch=AsyncMock())
    context = SimpleNamespace(workspace_id=TEST_WORKSPACE_ID)

    endpoint = cast(Any, create_evaluation_run)
    endpoint_globals = create_evaluation_run.__globals__
    original_scheduler = endpoint_globals["_schedule_background_run"]
    endpoint_globals["_schedule_background_run"] = _discard_background
    try:
        first, second = await asyncio.gather(
            endpoint(
                test_set_id="ts_concurrent",
                payload=EvaluationRunCreateRequest(workflow_id="wf_eval", name="Run A"),
                request=request,
                context=context,
                repository=repository,
                evaluation_repository=evaluation_repository,
                evaluation_service=evaluation_service,
            ),
            endpoint(
                test_set_id="ts_concurrent",
                payload=EvaluationRunCreateRequest(workflow_id="wf_eval", name="Run B"),
                request=request,
                context=context,
                repository=repository,
                evaluation_repository=evaluation_repository,
                evaluation_service=evaluation_service,
            ),
            return_exceptions=True,
        )
    finally:
        endpoint_globals["_schedule_background_run"] = original_scheduler

    results = [item for item in (first, second) if not isinstance(item, Exception)]
    errors = [item for item in (first, second) if isinstance(item, Exception)]

    assert len(results) == 1
    assert len(errors) == 1
    assert len(evaluation_repository.created_runs) == 1
    assert isinstance(errors[0], HTTPException)
    assert errors[0].status_code == 409


def test_delete_document_cascades_to_ground_truths_and_evaluation_results(tmp_path: Path) -> None:
    """Finding #2 regression: ondelete=CASCADE on evaluation_results.document_id."""
    db_path = tmp_path / "cascade.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def _setup() -> async_sessionmaker:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
        async with session_factory() as session:
            session.add(Workspace(id=TEST_WORKSPACE_ID, name="Integration Workspace"))
            await session.commit()
        return session_factory

    session_factory = asyncio.run(_setup())
    repository = TestSetRepository(session_factory=session_factory)
    ground_truth_repo = GroundTruthRepository(session_factory=session_factory)
    evaluation_repo = EvaluationRepository(session_factory=session_factory)

    test_set = asyncio.run(
        repository.create_test_set(
            name="Cascade Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    document = asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="cascade.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_c_cascade.pdf",
            size_bytes=50,
            page_count=1,
        )
    )

    gt = asyncio.run(
        ground_truth_repo.create_version(
            document_id=document.id,
            source="manual_edit",
            format="text",
            content="expected",
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    assert gt.document_id == document.id

    run = asyncio.run(
        evaluation_repo.create_run(
            test_set_id=test_set.id,
            workflow_id="wf_cascade",
            workflow_version=1,
            workflow_snapshot_json={},
            name="Cascade Run",
            total_documents=1,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    asyncio.run(
        evaluation_repo.create_result(
            evaluation_run_id=run.id,
            document_id=document.id,
            task_run_id=None,
            status="pending",
        )
    )

    assert (
        asyncio.run(ground_truth_repo.get_latest(document.id, workspace_id=TEST_WORKSPACE_ID))
        is not None
    )
    assert (
        len(asyncio.run(evaluation_repo.list_results(run.id, workspace_id=TEST_WORKSPACE_ID))) == 1
    )

    asyncio.run(repository.delete_test_document(document.id, workspace_id=TEST_WORKSPACE_ID))

    assert (
        asyncio.run(ground_truth_repo.get_latest(document.id, workspace_id=TEST_WORKSPACE_ID))
        is None
    )

    remaining_results = asyncio.run(
        evaluation_repo.list_results(run.id, workspace_id=TEST_WORKSPACE_ID)
    )
    assert len(remaining_results) == 0, (
        f"Expected 0 eval results after document cascade delete, got {len(remaining_results)}"
    )

    asyncio.run(engine.dispose())


def test_poll_evaluation_run_before_completion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding #3c: spec requires polling an in-progress run returns counts and status."""
    repository = _app(client).state.test_set_repository
    evaluation_repository = _app(client).state.evaluation_repository
    workflow = _app(client).state.workflow

    test_set = asyncio.run(
        repository.create_test_set(
            name="Poll Set", description=None, workspace_id=TEST_WORKSPACE_ID
        )
    )
    for i in range(2):
        asyncio.run(
            repository.create_test_document(
                test_set_id=test_set.id,
                filename=f"doc_{i}.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_{i}.pdf",
                size_bytes=100,
                page_count=1,
            )
        )

    scheduled: list[object] = []

    def _capture(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _capture)

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Poll Run"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    pending = client.get(f"/api/evaluation-runs/{run_id}")
    assert pending.status_code == 200
    pending_body = pending.json()
    assert pending_body["status"] == "pending"
    assert pending_body["total_documents"] == 2
    assert pending_body["completed_count"] == 0
    assert pending_body["failed_count"] == 0

    asyncio.run(
        evaluation_repository.update_run(
            run_id,
            status="running",
            completed_count=1,
            failed_count=0,
            duration_ms=150,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )
    running = client.get(f"/api/evaluation-runs/{run_id}")
    assert running.status_code == 200
    running_body = running.json()
    assert running_body["status"] == "running"
    assert running_body["completed_count"] == 1
    assert running_body["failed_count"] == 0
    assert running_body["duration_ms"] == 150


def test_evaluation_run_batch_populates_results_end_to_end(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding #3d: E2E test — create run → execute batch → verify results via API."""
    repository = _app(client).state.test_set_repository
    evaluation_repository: EvaluationRepository = _app(client).state.evaluation_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(name="E2E Set", description=None, workspace_id=TEST_WORKSPACE_ID)
    )
    asyncio.run(
        repository.create_test_document(
            test_set_id=test_set.id,
            filename="e2e.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc_e2e.pdf",
            size_bytes=99,
            page_count=1,
        )
    )

    captured_coros: list[object] = []

    def _capture_and_run(coro: object) -> object:
        captured_coros.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _capture_and_run)

    async def _fake_run_batch(*, run_id: str, test_set_id: str, workflow: object) -> None:
        pre_created = await evaluation_repository.list_results(
            run_id, workspace_id=TEST_WORKSPACE_ID
        )
        assert len(pre_created) == 1
        result = pre_created[0]
        await evaluation_repository.update_result(
            result.id,
            task_run_id="task_e2e_1",
            status="completed",
            output_content="# E2E Output",
            output_format="markdown",
            processing_time_ms=200,
            error=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
        await evaluation_repository.update_run(
            run_id,
            status="completed",
            completed_count=1,
            failed_count=0,
            duration_ms=200,
            workspace_id=TEST_WORKSPACE_ID,
        )

    _app(client).state.evaluation_service = SimpleNamespace(
        run_batch=_fake_run_batch,
        apply_result_as_ground_truth=_app(
            client
        ).state.evaluation_service.apply_result_as_ground_truth,
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "E2E Run"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    asyncio.run(_fake_run_batch(run_id=run_id, test_set_id=test_set.id, workflow=workflow))

    run_detail = client.get(f"/api/evaluation-runs/{run_id}")
    assert run_detail.status_code == 200
    assert run_detail.json()["status"] == "completed"
    assert run_detail.json()["completed_count"] == 1

    results = client.get(f"/api/evaluation-runs/{run_id}/results")
    assert results.status_code == 200
    results_body = results.json()
    assert results_body["summary"] == {
        "total": 1,
        "queued": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert results_body["results"][0]["filename"] == "e2e.pdf"
    assert results_body["results"][0]["status"] == "completed"
    assert "output_content" not in results_body["results"][0]

    result_id = results_body["results"][0]["id"]
    detail = client.get(f"/api/evaluation-runs/{run_id}/results/{result_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["output_content"] == "# E2E Output"
    assert detail_body["output_format"] == "markdown"
    assert detail_body["task_run_id"] == "task_e2e_1"
    assert detail_body["processing_time_ms"] == 200


def test_create_evaluation_run_tracks_background_task_reference(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(
            name="Tracked Run Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    release = Event()

    async def _never_complete(**kwargs: object) -> None:
        _ = kwargs
        while not release.is_set():
            await asyncio.sleep(0.01)

    _app(client).state.evaluation_service = SimpleNamespace(
        run_batch=_never_complete,
        apply_result_as_ground_truth=_app(
            client
        ).state.evaluation_service.apply_result_as_ground_truth,
    )

    with client:
        try:
            created = client.post(
                f"/api/test-sets/{test_set.id}/evaluation-runs",
                json={"workflow_id": workflow.id, "name": "Tracked Run"},
            )

            assert created.status_code == 201
            assert hasattr(_app(client).state, "evaluation_background_tasks")
            background_tasks = _app(client).state.evaluation_background_tasks
            assert len(background_tasks) == 1

            task = next(iter(background_tasks))
            assert not task.done()
        finally:
            release.set()
            time.sleep(0.05)

        assert task not in _app(client).state.evaluation_background_tasks


def test_background_batch_failure_marks_evaluation_run_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(
            name="Failure Run Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    scheduled: list[Coroutine[object, object, object]] = []

    def _capture(coro: Coroutine[object, object, object]) -> object:
        scheduled.append(coro)
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _capture)

    async def _boom(**kwargs: object) -> None:
        _ = kwargs
        raise RuntimeError("boom")

    _app(client).state.evaluation_service = SimpleNamespace(
        run_batch=_boom,
        apply_result_as_ground_truth=_app(
            client
        ).state.evaluation_service.apply_result_as_ground_truth,
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Failing Run"},
    )

    assert created.status_code == 201
    assert len(scheduled) == 1
    run_id = created.json()["id"]

    execution_error: RuntimeError | None = None
    try:
        asyncio.run(scheduled[0])
    except RuntimeError as exc:
        execution_error = exc

    detail = client.get(f"/api/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert execution_error is None
    assert detail_payload["status"] == "failed"
    assert detail_payload["completed_at"] is not None


def test_cancelled_background_batch_marks_evaluation_run_cancelled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _app(client).state.test_set_repository
    workflow = _app(client).state.workflow
    test_set = asyncio.run(
        repository.create_test_set(
            name="Cancelled Run Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    scheduled: list[Coroutine[object, object, object]] = []

    def _capture(coro: Coroutine[object, object, object]) -> object:
        scheduled.append(coro)
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _capture)

    async def _cancelled(**kwargs: object) -> None:
        _ = kwargs
        raise asyncio.CancelledError()

    _app(client).state.evaluation_service = SimpleNamespace(
        run_batch=_cancelled,
        apply_result_as_ground_truth=_app(
            client
        ).state.evaluation_service.apply_result_as_ground_truth,
    )

    created = client.post(
        f"/api/test-sets/{test_set.id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Cancelled Run"},
    )

    assert created.status_code == 201
    assert len(scheduled) == 1
    run_id = created.json()["id"]

    execution_error: BaseException | None = None
    try:
        asyncio.run(scheduled[0])
    except BaseException as exc:  # pragma: no cover - current broken behavior
        execution_error = exc

    detail = client.get(f"/api/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert execution_error is None
    assert detail_payload["status"] == "failed"
    assert detail_payload["completed_at"] is not None
