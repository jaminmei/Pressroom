from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from sqlalchemy import delete

from app.api.tasks import get_task_run_repository
from app.api.workflows import get_workflow_store
from app.main import app
from app.models.db.task_run import TaskRun
from app.models.db.workspace_member import WorkspaceMember
from app.models.workflow import WorkflowActor, WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.evaluation_repository import EvaluationRepository as AppEvaluationRepository
from app.repositories.test_set_repository import TestSetRepository as AppTestSetRepository
from app.services.workspace_permissions import WorkspaceRole
from tests.integration.workspace_api_support import (
    RegisteredClient,
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)


class _NoopEventStore:
    def compute_state(self, _run_id: str) -> dict[str, object]:
        return {}

    def delete_events_for_nodes(self, _run_id: str, _node_ids: set[str]) -> None:
        return None

    def get_events(self, _run_id: str) -> list[object]:
        return []


@dataclass(frozen=True, slots=True)
class ResourceCase:
    name: str
    create: Callable[[WorkspaceApiHarness, RegisteredClient, str], str]
    read_request: Callable[[TestClient, str], HttpxResponse]
    no_cap_request: Callable[[TestClient, str], HttpxResponse]


@pytest.fixture(autouse=True)
def _clear_cached_stores() -> None:
    get_workflow_store.cache_clear()
    get_task_run_repository.cache_clear()
    app.state.test_set_repository = AppTestSetRepository()
    app.state.evaluation_repository = AppEvaluationRepository()


def _sample_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/document", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )


def _switch_workspace(client: TestClient, workspace_id: str) -> None:
    response = client.post(f"/api/workspaces/{workspace_id}/switch")
    assert response.status_code == 200


def _prepare_task_state() -> None:
    app.state.running_tasks = {}
    app.state.event_store = _NoopEventStore()
    app.state.dag_scheduler = SimpleNamespace()
    app.state.engine_client = SimpleNamespace()


def _create_workflow_resource(
    _harness: WorkspaceApiHarness,
    owner: RegisteredClient,
    workspace_id: str,
) -> str:
    workflow = get_workflow_store().create(
        name="Scoped Workflow",
        definition=_sample_definition(),
        actor=WorkflowActor(user_id=owner.user_id, email="owner@example.com", name="Owner"),
        workspace_id=workspace_id,
    )
    return workflow.id


def _create_test_set_resource(
    _harness: WorkspaceApiHarness,
    _owner: RegisteredClient,
    workspace_id: str,
) -> str:
    record = asyncio.run(
        app.state.test_set_repository.create_test_set(
            name="Scoped Test Set",
            description=None,
            workspace_id=workspace_id,
        )
    )
    return record.id


def _create_task_run_resource(
    harness: WorkspaceApiHarness,
    _owner: RegisteredClient,
    workspace_id: str,
) -> str:
    _prepare_task_state()
    task_id = f"task_{workspace_id[-8:]}"
    now = datetime.now(timezone.utc)
    with harness.session_factory() as session:
        session.add(
            TaskRun(
                id=task_id,
                status="completed",
                workspace_id=workspace_id,
                created_at=now,
                completed_at=now,
                results_json='[{"result_id":"r1","content":"ok"}]',
                updated_at=now,
            )
        )
        session.commit()
    return task_id


def _create_evaluation_run_resource(
    _harness: WorkspaceApiHarness,
    _owner: RegisteredClient,
    workspace_id: str,
) -> str:
    run = asyncio.run(
        app.state.evaluation_repository.create_run(
            test_set_id=f"ts_{workspace_id[-8:]}",
            workflow_id=f"wf_{workspace_id[-8:]}",
            workflow_version=1,
            workflow_snapshot_json={},
            name="Scoped Evaluation",
            total_documents=0,
            workspace_id=workspace_id,
        )
    )
    return run.id


RESOURCE_CASES = [
    ResourceCase(
        name="workflow",
        create=_create_workflow_resource,
        read_request=lambda client, resource_id: client.get(f"/api/workflows/{resource_id}"),
        no_cap_request=lambda client, resource_id: client.post(
            f"/api/workflows/{resource_id}/publish"
        ),
    ),
    ResourceCase(
        name="test_set",
        create=_create_test_set_resource,
        read_request=lambda client, resource_id: client.get(f"/api/test-sets/{resource_id}"),
        no_cap_request=lambda client, resource_id: client.patch(
            f"/api/test-sets/{resource_id}",
            json={"name": "Blocked Rename"},
        ),
    ),
    ResourceCase(
        name="task_run",
        create=_create_task_run_resource,
        read_request=lambda client, resource_id: client.get(f"/api/tasks/{resource_id}"),
        no_cap_request=lambda client, resource_id: client.post(f"/api/tasks/{resource_id}/retry"),
    ),
    ResourceCase(
        name="evaluation_run",
        create=_create_evaluation_run_resource,
        read_request=lambda client, resource_id: client.get(f"/api/evaluation-runs/{resource_id}"),
        no_cap_request=lambda client, resource_id: client.post(
            f"/api/evaluation-runs/{resource_id}/cancel"
        ),
    ),
]


@pytest.mark.parametrize("resource_case", RESOURCE_CASES, ids=lambda case: case.name)
def test_non_member_direct_url_returns_404(
    workspace_api_harness: WorkspaceApiHarness,
    resource_case: ResourceCase,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    outsider = workspace_api_harness.register_user("outsider@example.com", "Outsider")
    target_workspace_id = create_workspace(owner.client, name="Target")
    outsider_workspace_id = create_workspace(outsider.client, name="Outsider")
    _switch_workspace(owner.client, target_workspace_id)
    _switch_workspace(outsider.client, outsider_workspace_id)
    resource_id = resource_case.create(workspace_api_harness, owner, target_workspace_id)

    response = resource_case.read_request(
        outsider.client,
        resource_id,
    )

    assert response.status_code == 404


@pytest.mark.parametrize("resource_case", RESOURCE_CASES, ids=lambda case: case.name)
def test_same_workspace_without_capability_returns_403(
    workspace_api_harness: WorkspaceApiHarness,
    resource_case: ResourceCase,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    viewer = workspace_api_harness.register_user("viewer@example.com", "Viewer")
    workspace_id = create_workspace(owner.client, name="Shared")
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=viewer.user_id,
        role=WorkspaceRole.VIEWER.value,
    )
    _switch_workspace(owner.client, workspace_id)
    _switch_workspace(viewer.client, workspace_id)
    resource_id = resource_case.create(workspace_api_harness, owner, workspace_id)

    response = resource_case.no_cap_request(viewer.client, resource_id)

    assert response.status_code == 403


@pytest.mark.parametrize("resource_case", RESOURCE_CASES, ids=lambda case: case.name)
def test_cross_workspace_idor_returns_404(
    workspace_api_harness: WorkspaceApiHarness,
    resource_case: ResourceCase,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_a = create_workspace(owner.client, name="Workspace A")
    workspace_b = create_workspace(owner.client, name="Workspace B")
    _switch_workspace(owner.client, workspace_a)
    resource_id = resource_case.create(workspace_api_harness, owner, workspace_a)
    _switch_workspace(owner.client, workspace_b)

    response = resource_case.read_request(owner.client, resource_id)

    assert response.status_code == 404


@pytest.mark.parametrize("resource_case", RESOURCE_CASES, ids=lambda case: case.name)
def test_revoked_credentials_return_401(
    workspace_api_harness: WorkspaceApiHarness,
    resource_case: ResourceCase,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client, name="Revoked")
    _switch_workspace(owner.client, workspace_id)
    resource_id = resource_case.create(workspace_api_harness, owner, workspace_id)
    logout_response = owner.client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    response = resource_case.read_request(owner.client, resource_id)

    assert response.status_code == 401


@pytest.mark.parametrize("resource_case", RESOURCE_CASES, ids=lambda case: case.name)
def test_stale_workspace_membership_context_returns_404(
    workspace_api_harness: WorkspaceApiHarness,
    resource_case: ResourceCase,
) -> None:
    owner = workspace_api_harness.register_user("owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client, name="Stale")
    _switch_workspace(owner.client, workspace_id)
    resource_id = resource_case.create(workspace_api_harness, owner, workspace_id)
    with workspace_api_harness.session_factory() as session:
        session.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == owner.user_id,
            )
        )
        session.commit()

    response = resource_case.read_request(owner.client, resource_id)

    assert response.status_code == 404
