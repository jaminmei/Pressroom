from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import get_authenticated_context
from app.api.evaluation_runs import router as evaluation_runs_router
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.workflow_store import WorkflowStore
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from tests._workspace_fixture import make_user, make_workspace_with_member
from tests.integration.workspace_api_support import reset_db_runtime


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
def evaluation_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FastAPI]:
    database_path = tmp_path / "evaluation-api-contract.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    app = FastAPI()
    app.include_router(evaluation_runs_router, prefix="/api")
    app.state.test_set_repository = TestSetRepository(session_factory=session_factory)
    app.state.ground_truth_repository = GroundTruthRepository(session_factory=session_factory)
    app.state.evaluation_repository = EvaluationRepository(session_factory=session_factory)
    app.state.evaluation_dispatch_repository = EvaluationDispatchRepository(
        session_factory=session_factory
    )
    app.state.workflow_store = WorkflowStore()

    async def _run_batch(**kwargs: object) -> None:
        return None

    async def _cancel_run(run_id: str, *, workspace_id: str) -> Any:
        return await app.state.evaluation_repository.cancel_run(run_id, workspace_id=workspace_id)

    app.state.evaluation_service = SimpleNamespace(
        run_batch=_run_batch,
        cancel_run=_cancel_run,
    )
    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def _set_context(
    app: FastAPI, *, user_id: str, email: str, workspace_id: str, role: WorkspaceRole
) -> None:
    session = AuthSessionInfo(
        id=f"session-{user_id}",
        user_id=user_id,
        expires_at=datetime.now(timezone.utc),
    )
    context = AuthenticatedContext.model_validate(
        {
            "user": AuthUser(id=user_id, email=email),
            "session": session,
            "workspace_id": workspace_id,
            "role": role.value,
            "capabilities": sorted(CAPABILITIES[role]),
        }
    )
    app.dependency_overrides[get_authenticated_context] = lambda: context


def _make_member(email: str, role: WorkspaceRole) -> tuple[str, str]:
    user_id = make_user(db_session.SessionLocal, email)
    workspace_id = make_workspace_with_member(
        db_session.SessionLocal,
        owner_user_id=user_id,
        member_role=role,
    )
    return user_id, workspace_id


async def _create_test_set_with_documents(
    app: FastAPI, *, workspace_id: str, document_count: int = 1
) -> tuple[str, list[str]]:
    test_set = await app.state.test_set_repository.create_test_set(
        name="Evaluation Set",
        description=None,
        workspace_id=workspace_id,
    )
    document_ids: list[str] = []
    for index in range(document_count):
        document = await app.state.test_set_repository.create_test_document(
            test_set_id=test_set.id,
            filename=f"doc-{index}.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/documents/doc-{index}.pdf",
            size_bytes=10,
            page_count=1,
        )
        document_ids.append(document.id)
    return test_set.id, document_ids


# ----- 4.13: POST /test-sets/{ts}/evaluation-runs contract -----


def test_create_evaluation_run_returns_201_in_serial_mode(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("creator@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, _doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    scheduled: list[object] = []

    def _track(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _track)
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="creator@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Serial run"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["total_documents"] == 1
    assert len(scheduled) == 1


def test_create_evaluation_run_skips_background_task_in_queue_mode(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("queue@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Q",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    scheduled: list[object] = []

    def _track(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _track)
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="queue@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Queue run"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert scheduled == []
    outbox_rows = asyncio.run(
        evaluation_app.state.evaluation_dispatch_repository.list_for_run(response.json()["id"])
    )
    assert len(outbox_rows) == len(doc_ids)


def test_create_evaluation_run_is_idempotent_for_client_request_id(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("idempo@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF I",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, _doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )

    def _swallow(coro: object) -> object:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _swallow)
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="idempo@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )

    payload = {
        "workflow_id": workflow.id,
        "name": "Idempo",
        "client_request_id": "cli_req_evaluation_idempo",
    }
    first = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs", json=payload
    )
    second = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs", json=payload
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_create_evaluation_run_404_for_missing_test_set(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("missing@example.com", WorkspaceRole.RUNNER)
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="missing@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(
        "/api/test-sets/ts_missing/evaluation-runs",
        json={"workflow_id": "wf_anything"},
    )
    assert response.status_code == 404


def test_create_evaluation_run_404_for_missing_workflow(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("nowf@example.com", WorkspaceRole.RUNNER)
    test_set_id, _ = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="nowf@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": "wf_missing"},
    )
    assert response.status_code == 404


def test_create_evaluation_run_422_for_invalid_document_ids(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("baddocs@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Bad",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, _ = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="baddocs@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id, "document_ids": ["doc_missing"]},
    )
    assert response.status_code == 422


def test_create_evaluation_run_409_when_active_run_exists(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("conflict@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF C",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Existing",
            total_documents=1,
            document_ids=doc_ids,
            workspace_id=workspace_id,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="conflict@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id},
    )
    assert response.status_code == 409


def test_create_evaluation_run_403_when_role_lacks_capability(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("viewer@example.com", WorkspaceRole.VIEWER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF V",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, _ = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="viewer@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER,
    )
    response = TestClient(evaluation_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id},
    )
    assert response.status_code == 403


# ----- 4.14: POST /evaluation-runs/{id}/cancel contract -----


def test_cancel_evaluation_run_returns_200_with_already_cancelled_false(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("canceler@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Cancel",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    run, _results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Cancelable",
            total_documents=1,
            document_ids=doc_ids,
            workspace_id=workspace_id,
            queue_mode=True,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="canceler@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(evaluation_app).post(f"/api/evaluation-runs/{run.id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["already_cancelled"] is False
    assert body["revoked_task_count"] == 0


def test_cancel_evaluation_run_is_idempotent_for_already_cancelled(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("recanceler@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Re",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    run, _results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Re-cancelable",
            total_documents=1,
            document_ids=doc_ids,
            workspace_id=workspace_id,
            queue_mode=True,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="recanceler@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    client = TestClient(evaluation_app)
    first = client.post(f"/api/evaluation-runs/{run.id}/cancel")
    second = client.post(f"/api/evaluation-runs/{run.id}/cancel")

    assert first.status_code == 200
    assert first.json()["already_cancelled"] is False
    assert second.status_code == 200
    assert second.json()["already_cancelled"] is True


def test_cancel_evaluation_run_404_for_missing_run(evaluation_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("cancelmissing@example.com", WorkspaceRole.RUNNER)
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="cancelmissing@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post("/api/evaluation-runs/eval_run_missing/cancel")
    assert response.status_code == 404


def test_cancel_evaluation_run_409_for_terminal_completed_run(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("terminal@example.com", WorkspaceRole.RUNNER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Terminal",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id)
    )
    run, results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Terminal",
            total_documents=1,
            document_ids=doc_ids,
            workspace_id=workspace_id,
        )
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="done",
            output_format="markdown",
            processing_time_ms=10,
            error=None,
            task_run_results=[],
            task_run_node_summary={"total": 1, "completed": 1, "failed": 0},
            task_run_result_preview="done",
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="terminal@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(f"/api/evaluation-runs/{run.id}/cancel")
    assert response.status_code == 409


def test_cancel_evaluation_run_404_for_cross_workspace_access(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_a, ws_a = _make_member("wsa@example.com", WorkspaceRole.RUNNER)
    user_b, ws_b = _make_member("wsb@example.com", WorkspaceRole.RUNNER)
    workflow_a = evaluation_app.state.workflow_store.create(
        name="WF A",
        definition=_sample_definition(),
        workspace_id=ws_a,
    )
    test_set_id_a, doc_ids_a = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=ws_a)
    )
    run, _results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id_a,
            workflow_id=workflow_a.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="WS A run",
            total_documents=1,
            document_ids=doc_ids_a,
            workspace_id=ws_a,
            queue_mode=True,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_b,
        email="wsb@example.com",
        workspace_id=ws_b,
        role=WorkspaceRole.RUNNER,
    )
    response = TestClient(evaluation_app).post(f"/api/evaluation-runs/{run.id}/cancel")
    assert response.status_code == 404


# ----- 4.15: GET /evaluation-runs/{id}/results summary fields -----


def test_results_summary_includes_queued_running_skipped_counts(
    evaluation_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    user_id, workspace_id = _make_member("summary@example.com", WorkspaceRole.VIEWER)
    workflow = evaluation_app.state.workflow_store.create(
        name="WF Summary",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_id, document_count=4)
    )
    run, results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Summary run",
            total_documents=4,
            document_ids=doc_ids,
            workspace_id=workspace_id,
        )
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="done-1",
            output_format="markdown",
            processing_time_ms=10,
            error=None,
            task_run_results=[],
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.finalize_result(
            results[1].id,
            outcome_status="failed",
            output_content=None,
            output_format=None,
            processing_time_ms=5,
            error="boom",
            task_run_results=[],
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="summary@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER,
    )
    response = TestClient(evaluation_app).get(f"/api/evaluation-runs/{run.id}/results")
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert set(summary.keys()) >= {"total", "completed", "failed", "queued", "running", "skipped"}
    assert summary["total"] == 4
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["queued"] == 2
    assert summary["running"] == 0
    assert summary["skipped"] == 0


def test_result_and_review_responses_include_current_gt_availability(
    evaluation_app: FastAPI,
) -> None:
    user_id, workspace_id = _make_member("gt-availability@example.com", WorkspaceRole.EDITOR)
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(
            evaluation_app,
            workspace_id=workspace_id,
            document_count=2,
        )
    )
    run, results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id="wf-gt-availability",
            workflow_version=1,
            workflow_snapshot_json={},
            name="GT availability",
            total_documents=2,
            document_ids=doc_ids,
            workspace_id=workspace_id,
        )
    )
    for index, result in enumerate(results):
        asyncio.run(
            evaluation_app.state.evaluation_repository.finalize_result(
                result.id,
                outcome_status="completed",
                output_content=f"result-{index}",
                output_format="text",
                processing_time_ms=10,
                error=None,
                task_run_results=[],
                task_run_node_summary=None,
                task_run_result_preview=None,
            )
        )
    asyncio.run(
        evaluation_app.state.ground_truth_repository.create_version(
            document_id=doc_ids[0],
            source="manual",
            format="text",
            content="existing",
            workspace_id=workspace_id,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="gt-availability@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.EDITOR,
    )
    client = TestClient(evaluation_app)

    listed = client.get(f"/api/evaluation-runs/{run.id}/results")
    assert listed.status_code == 200
    listed_results = listed.json()["results"]
    listed_by_document = {item["document_id"]: item for item in listed_results}
    assert listed_by_document[doc_ids[0]]["has_ground_truth"] is True
    assert listed_by_document[doc_ids[1]]["has_ground_truth"] is False

    rejected = client.post(f"/api/evaluation-runs/{run.id}/results/{results[0].id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["has_ground_truth"] is True

    accepted = client.post(
        f"/api/evaluation-runs/{run.id}/results/{results[1].id}/accept-as-ground-truth"
    )
    assert accepted.status_code == 200
    assert accepted.json()["has_ground_truth"] is True

    refreshed = client.get(f"/api/evaluation-runs/{run.id}/results")
    assert all(item["has_ground_truth"] is True for item in refreshed.json()["results"])


# ----- Document-scoped evaluation run history -----


def test_document_run_history_is_scoped_ordered_and_paginated(
    evaluation_app: FastAPI,
) -> None:
    user_id, workspace_id = _make_member("doc-history@example.com", WorkspaceRole.VIEWER)
    workflow = evaluation_app.state.workflow_store.create(
        name="OCR History",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, doc_ids = asyncio.run(
        _create_test_set_with_documents(
            evaluation_app,
            workspace_id=workspace_id,
            document_count=2,
        )
    )

    older_run, older_results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Older run",
            total_documents=2,
            document_ids=doc_ids,
            workspace_id=workspace_id,
        )
    )
    for index, result in enumerate(older_results):
        asyncio.run(
            evaluation_app.state.evaluation_repository.update_result(
                result.id,
                task_run_id=None,
                status="completed",
                output_content=f"done-{index}",
                output_format="markdown",
                processing_time_ms=4100 + index,
                error=None,
                workspace_id=workspace_id,
            )
        )
    asyncio.run(
        evaluation_app.state.evaluation_repository.update_run(
            older_run.id,
            status="completed",
            completed_count=2,
            failed_count=0,
            duration_ms=9000,
            started_at=older_run.created_at,
            completed_at=older_run.created_at,
            workspace_id=workspace_id,
        )
    )

    latest_run, latest_results = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=1,
            workflow_snapshot_json={},
            name="Latest run",
            total_documents=1,
            document_ids=[doc_ids[0]],
            workspace_id=workspace_id,
        )
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.update_result(
            latest_results[0].id,
            task_run_id=None,
            status="failed",
            output_content=None,
            output_format=None,
            processing_time_ms=2200,
            error="OCR timeout",
            workspace_id=workspace_id,
        )
    )
    asyncio.run(
        evaluation_app.state.evaluation_repository.update_run(
            latest_run.id,
            status="failed",
            completed_count=0,
            failed_count=1,
            duration_ms=2500,
            started_at=latest_run.created_at,
            completed_at=latest_run.created_at,
            workspace_id=workspace_id,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_id,
        email="doc-history@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER,
    )

    client = TestClient(evaluation_app)
    response = client.get(f"/api/test-sets/{test_set_id}/documents/{doc_ids[0]}/evaluation-runs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["run_id"] for item in body["items"]] == [
        latest_run.id,
        older_run.id,
    ]
    assert body["items"][0] == {
        "run_id": latest_run.id,
        "result_id": latest_results[0].id,
        "run_name": "Latest run",
        "workflow_id": workflow.id,
        "workflow_name": "OCR History",
        "run_status": "failed",
        "result_status": "failed",
        "processing_time_ms": 2200,
        "error": "OCR timeout",
        "comparison_status": "not_compared",
        "review_status": "unreviewed",
        "created_at": latest_run.created_at.isoformat(),
        "completed_at": latest_run.created_at.isoformat(),
        "run_duration_ms": 2500,
    }

    page = client.get(
        f"/api/test-sets/{test_set_id}/documents/{doc_ids[0]}/evaluation-runs",
        params={"limit": 1, "offset": 1},
    ).json()
    assert page["total"] == 2
    assert [item["run_id"] for item in page["items"]] == [older_run.id]

    other_document = client.get(
        f"/api/test-sets/{test_set_id}/documents/{doc_ids[1]}/evaluation-runs"
    ).json()
    assert other_document["total"] == 1
    assert [item["run_id"] for item in other_document["items"]] == [older_run.id]


def test_document_run_history_hides_mismatched_and_cross_workspace_resources(
    evaluation_app: FastAPI,
) -> None:
    user_a, workspace_a = _make_member("doc-history-a@example.com", WorkspaceRole.VIEWER)
    user_b, workspace_b = _make_member("doc-history-b@example.com", WorkspaceRole.VIEWER)
    test_set_a, document_ids_a = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_a)
    )
    test_set_b, document_ids_b = asyncio.run(
        _create_test_set_with_documents(evaluation_app, workspace_id=workspace_a)
    )
    run, _ = asyncio.run(
        evaluation_app.state.evaluation_repository.create_run_with_results(
            test_set_id=test_set_a,
            workflow_id="deleted-workflow",
            workflow_version=1,
            workflow_snapshot_json={},
            name=None,
            total_documents=1,
            document_ids=document_ids_a,
            workspace_id=workspace_a,
        )
    )
    _set_context(
        evaluation_app,
        user_id=user_a,
        email="doc-history-a@example.com",
        workspace_id=workspace_a,
        role=WorkspaceRole.VIEWER,
    )
    client = TestClient(evaluation_app)

    missing_workflow = client.get(
        f"/api/test-sets/{test_set_a}/documents/{document_ids_a[0]}/evaluation-runs"
    )
    assert missing_workflow.status_code == 200
    assert missing_workflow.json()["items"][0]["run_id"] == run.id
    assert missing_workflow.json()["items"][0]["workflow_name"] is None

    mismatched = client.get(
        f"/api/test-sets/{test_set_a}/documents/{document_ids_b[0]}/evaluation-runs"
    )
    assert mismatched.status_code == 404

    _set_context(
        evaluation_app,
        user_id=user_b,
        email="doc-history-b@example.com",
        workspace_id=workspace_b,
        role=WorkspaceRole.VIEWER,
    )
    cross_workspace = client.get(
        f"/api/test-sets/{test_set_a}/documents/{document_ids_a[0]}/evaluation-runs"
    )
    assert cross_workspace.status_code == 404
