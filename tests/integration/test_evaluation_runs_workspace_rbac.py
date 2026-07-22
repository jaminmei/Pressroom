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

from app.api.auth import get_authenticated_context
from app.api.evaluation_runs import router as evaluation_runs_router
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
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
def rbac_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FastAPI]:
    database_path = tmp_path / "evaluation-runs-workspace-rbac.sqlite3"
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
    app.state.workflow_store = WorkflowStore()

    async def _run_batch(**kwargs: object) -> None:
        _ = kwargs

    app.state.evaluation_service = SimpleNamespace(run_batch=_run_batch)
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


async def _create_test_set_with_document(app: FastAPI, *, workspace_id: str) -> tuple[str, str]:
    test_set = await app.state.test_set_repository.create_test_set(
        name="RBAC Set",
        description=None,
        workspace_id=workspace_id,
    )
    document = await app.state.test_set_repository.create_test_document(
        test_set_id=test_set.id,
        filename="invoice.pdf",
        mime_type="application/pdf",
        storage_path=f"test_sets/{test_set.id}/documents/invoice.pdf",
        size_bytes=100,
        page_count=1,
    )
    return test_set.id, document.id


def test_runner_can_create_evaluation_run(
    rbac_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, workspace_id = _make_member("runner@example.com", WorkspaceRole.RUNNER)
    workflow = rbac_app.state.workflow_store.create(
        name="Runnable Workflow",
        definition=_sample_definition(),
        workspace_id=workspace_id,
    )
    test_set_id, _document_id = asyncio.run(
        _create_test_set_with_document(rbac_app, workspace_id=workspace_id)
    )
    scheduled: list[object] = []

    def _discard(coro: object) -> object:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr("app.api.evaluation_runs._schedule_background_run", _discard)
    _set_context(
        rbac_app,
        user_id=user_id,
        email="runner@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.RUNNER,
    )

    response = TestClient(rbac_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Runner Run"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert len(scheduled) == 1


def test_viewer_cannot_cancel_evaluation_run(rbac_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("viewer@example.com", WorkspaceRole.VIEWER)
    run = asyncio.run(
        rbac_app.state.evaluation_repository.create_run(
            test_set_id="ts_cancel",
            workflow_id="wf_cancel",
            workflow_version=1,
            workflow_snapshot_json={},
            name="Cancelable Run",
            total_documents=0,
            workspace_id=workspace_id,
        )
    )
    _set_context(
        rbac_app,
        user_id=user_id,
        email="viewer@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER,
    )

    response = TestClient(rbac_app).post(f"/api/evaluation-runs/{run.id}/cancel")

    assert response.status_code == 403
    assert response.json()["detail"] == "run.cancel required"


def test_cross_workflow_dataset_workspace_returns_404(
    rbac_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, dataset_workspace_id = _make_member("owner@example.com", WorkspaceRole.OWNER)
    _other_user_id, workflow_workspace_id = _make_member("other@example.com", WorkspaceRole.OWNER)
    workflow = rbac_app.state.workflow_store.create(
        name="Other Workflow",
        definition=_sample_definition(),
        workspace_id=workflow_workspace_id,
    )
    test_set_id, _document_id = asyncio.run(
        _create_test_set_with_document(rbac_app, workspace_id=dataset_workspace_id)
    )
    monkeypatch.setattr(
        "app.api.evaluation_runs._schedule_background_run",
        lambda coro: SimpleNamespace(close=getattr(coro, "close", lambda: None)()),
    )
    _set_context(
        rbac_app,
        user_id=user_id,
        email="owner@example.com",
        workspace_id=dataset_workspace_id,
        role=WorkspaceRole.OWNER,
    )

    response = TestClient(rbac_app).post(
        f"/api/test-sets/{test_set_id}/evaluation-runs",
        json={"workflow_id": workflow.id, "name": "Invalid Pair"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"Workflow not found: {workflow.id}"


def test_cross_workspace_run_get_returns_404(rbac_app: FastAPI) -> None:
    user_id, caller_workspace_id = _make_member("owner-a@example.com", WorkspaceRole.OWNER)
    _other_user_id, other_workspace_id = _make_member("owner-b@example.com", WorkspaceRole.OWNER)
    run = asyncio.run(
        rbac_app.state.evaluation_repository.create_run(
            test_set_id="ts_private",
            workflow_id="wf_private",
            workflow_version=1,
            workflow_snapshot_json={},
            name="Private Run",
            total_documents=0,
            workspace_id=other_workspace_id,
        )
    )
    _set_context(
        rbac_app,
        user_id=user_id,
        email="owner-a@example.com",
        workspace_id=caller_workspace_id,
        role=WorkspaceRole.OWNER,
    )

    response = TestClient(rbac_app).get(f"/api/evaluation-runs/{run.id}")

    assert response.status_code == 404


def test_null_workspace_evaluation_run_is_hidden_when_enforced(rbac_app: FastAPI) -> None:
    user_id, workspace_id = _make_member("owner-null@example.com", WorkspaceRole.OWNER)
    run = asyncio.run(
        rbac_app.state.evaluation_repository.create_run(
            test_set_id="ts_legacy",
            workflow_id="wf_legacy",
            workflow_version=1,
            workflow_snapshot_json={},
            name="Legacy Null Run",
            total_documents=0,
            workspace_id=None,
        )
    )
    _set_context(
        rbac_app,
        user_id=user_id,
        email="owner-null@example.com",
        workspace_id=workspace_id,
        role=WorkspaceRole.OWNER,
    )

    response = TestClient(rbac_app).get(f"/api/evaluation-runs/{run.id}")

    assert response.status_code == 404
