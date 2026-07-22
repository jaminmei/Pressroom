from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import workflows as workflow_api
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.auth import AuthUser
from app.models.db.workspace_member import WorkspaceMember
from app.models.workflow import WorkflowDefinition
from app.services.database_workflow_store import DatabaseWorkflowStore
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


def _sample_definition(encoding: str = "utf-8") -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": encoding}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }


async def _skip_discover_seed_configs(_: object) -> int:
    return 0


def _reset_db_runtime() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    workflow_api.get_workflow_store.cache_clear()


@dataclass(frozen=True, slots=True)
class WorkflowRbacHarness:
    workspace_id: str
    users: dict[WorkspaceRole, AuthUser]
    session_factory: Callable[[], Session]
    execution_service: _FakeExecutionService

    def client(self, role: WorkspaceRole) -> TestClient:
        return make_workspace_client(
            app,
            user=self.users[role],
            workspace_id=self.workspace_id,
            role=role,
        )

    def create_workflow(self, *, workspace_id: str | None = None):
        return DatabaseWorkflowStore(session_factory=self.session_factory).create(
            name="Seed workflow",
            definition=WorkflowDefinition.model_validate(_sample_definition()),
            workspace_id=workspace_id or self.workspace_id,
        )


@pytest.fixture()
def workflow_rbac_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> Iterator[WorkflowRbacHarness]:
    database_path = tmp_path / "workflow-rbac.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    enable_rbac(monkeypatch)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", _skip_discover_seed_configs)
    execution_service = _FakeExecutionService()
    monkeypatch.setattr(
        "app.main.WorkflowExecutionService",
        lambda _orchestrator: execution_service,
    )
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    session_factory = db_session.SessionLocal
    owner_id = make_user(session_factory, "owner@example.com")
    workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    users = {
        WorkspaceRole.OWNER: AuthUser(id=owner_id, email="owner@example.com"),
    }
    with session_factory() as session:
        for role in (
            WorkspaceRole.ADMIN,
            WorkspaceRole.EDITOR,
            WorkspaceRole.RUNNER,
            WorkspaceRole.VIEWER,
        ):
            email = f"{role.value}@example.com"
            user_id = make_user(session_factory, email)
            users[role] = AuthUser(id=user_id, email=email)
            session.add(
                WorkspaceMember(
                    id=f"wsm_{role.value}",
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=role.value,
                )
            )
        session.commit()

    yield WorkflowRbacHarness(
        workspace_id=workspace_id,
        users=users,
        session_factory=session_factory,
        execution_service=execution_service,
    )

    app.dependency_overrides.clear()
    workflow_api.get_workflow_store.cache_clear()


class _FakeExecutionService:
    def __init__(self) -> None:
        self.definitions: list[WorkflowDefinition] = []

    async def execute(
        self,
        definition: WorkflowDefinition,
        _execution: object,
    ) -> SimpleNamespace:
        self.definitions.append(definition)
        return SimpleNamespace(
            task_id="task_rbac",
            status=SimpleNamespace(value="queued"),
            created_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (
            WorkspaceRole.OWNER,
            {"create": 201, "save": 200, "publish": 200, "execute": 202, "delete": 200},
        ),
        (
            WorkspaceRole.ADMIN,
            {"create": 201, "save": 200, "publish": 200, "execute": 202, "delete": 200},
        ),
        (
            WorkspaceRole.EDITOR,
            {"create": 201, "save": 200, "publish": 403, "execute": 202, "delete": 403},
        ),
        (
            WorkspaceRole.RUNNER,
            {"create": 403, "save": 403, "publish": 403, "execute": 202, "delete": 403},
        ),
        (
            WorkspaceRole.VIEWER,
            {"create": 403, "save": 403, "publish": 403, "execute": 403, "delete": 403},
        ),
    ],
)
def test_workflow_endpoints_enforce_role_capabilities(
    workflow_rbac_harness: WorkflowRbacHarness,
    role: WorkspaceRole,
    expected: dict[str, int],
) -> None:
    seeded = workflow_rbac_harness.create_workflow()

    with workflow_rbac_harness.client(role) as client:
        list_response = client.get("/api/workflows")
        get_response = client.get(f"/api/workflows/{seeded.id}")
        create_response = client.post(
            "/api/workflows",
            json={"name": f"Create as {role.value}", "definition": _sample_definition()},
        )
        save_response = client.post(
            "/api/workflows/save",
            json={"name": f"Save as {role.value}", "definition": _sample_definition("big5")},
        )
        publish_response = client.post(f"/api/workflows/{seeded.id}/publish")
        execute_response = client.post(f"/api/workflows/{seeded.id}/execute", json={"file_ids": []})
        delete_target = workflow_rbac_harness.create_workflow()
        delete_response = client.delete(f"/api/workflows/{delete_target.id}")

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert create_response.status_code == expected["create"]
    assert save_response.status_code == expected["save"]
    assert publish_response.status_code == expected["publish"]
    assert execute_response.status_code == expected["execute"]
    assert delete_response.status_code == expected["delete"]


def test_cross_workspace_workflow_id_returns_404(
    workflow_rbac_harness: WorkflowRbacHarness,
) -> None:
    other_owner_id = make_user(workflow_rbac_harness.session_factory, "other-owner@example.com")
    other_workspace_id = make_workspace_with_member(
        workflow_rbac_harness.session_factory,
        owner_user_id=other_owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    other_workflow = workflow_rbac_harness.create_workflow(workspace_id=other_workspace_id)

    with workflow_rbac_harness.client(WorkspaceRole.OWNER) as client:
        response = client.get(f"/api/workflows/{other_workflow.id}")

    assert response.status_code == 404


def test_cross_workspace_direct_version_routes_return_404(
    workflow_rbac_harness: WorkflowRbacHarness,
) -> None:
    other_owner_id = make_user(workflow_rbac_harness.session_factory, "version-owner@example.com")
    other_workspace_id = make_workspace_with_member(
        workflow_rbac_harness.session_factory,
        owner_user_id=other_owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    other_workflow = workflow_rbac_harness.create_workflow(workspace_id=other_workspace_id)
    assert other_workflow.workflow_key is not None

    with workflow_rbac_harness.client(WorkspaceRole.OWNER) as client:
        by_id = client.get(f"/api/workflows/{other_workflow.id}/versions/1")
        by_key = client.get(f"/api/workflows/{other_workflow.workflow_key}/versions/1")

    assert by_id.status_code == 404
    assert by_key.status_code == 404


def test_runner_executes_persisted_saved_version(
    workflow_rbac_harness: WorkflowRbacHarness,
) -> None:
    seeded = workflow_rbac_harness.create_workflow()

    with workflow_rbac_harness.client(WorkspaceRole.RUNNER) as client:
        response = client.post(
            f"/api/workflows/{seeded.id}/execute",
            json={"version": 1, "file_ids": [], "run_name": "runner saved run"},
        )

    assert response.status_code == 202
    assert workflow_rbac_harness.execution_service.definitions[-1].nodes[1].config == {
        "encoding": "utf-8"
    }


def test_runner_cannot_tamper_with_persisted_definition(
    workflow_rbac_harness: WorkflowRbacHarness,
) -> None:
    seeded = workflow_rbac_harness.create_workflow()

    with workflow_rbac_harness.client(WorkspaceRole.RUNNER) as client:
        response = client.post(
            f"/api/workflows/{seeded.id}/execute",
            json={"file_ids": [], "definition": _sample_definition("tampered")},
        )

    assert response.status_code == 422
    assert workflow_rbac_harness.execution_service.definitions == []


def test_foreign_workflow_version_execute_returns_404(
    workflow_rbac_harness: WorkflowRbacHarness,
) -> None:
    other_owner_id = make_user(workflow_rbac_harness.session_factory, "execute-owner@example.com")
    other_workspace_id = make_workspace_with_member(
        workflow_rbac_harness.session_factory,
        owner_user_id=other_owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    other_workflow = workflow_rbac_harness.create_workflow(workspace_id=other_workspace_id)

    with workflow_rbac_harness.client(WorkspaceRole.RUNNER) as client:
        response = client.post(
            f"/api/workflows/{other_workflow.id}/execute",
            json={"version": 1, "file_ids": []},
        )

    assert response.status_code == 404
