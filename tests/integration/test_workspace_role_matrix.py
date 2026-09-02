from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import require_workspace_capability
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthUser
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    enable_rbac,
    make_user,
    make_workspace_client,
    make_workspace_with_member,
)


def _reset_db_runtime() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@dataclass(frozen=True, slots=True)
class EndpointCase:
    name: str
    method: str
    path: str
    allowed_roles: frozenset[WorkspaceRole]


@dataclass(frozen=True, slots=True)
class WorkspaceRoleMatrixHarness:
    app: FastAPI
    workspace_id: str
    users: dict[WorkspaceRole, AuthUser]
    session_factory: Callable[[], Session]

    def client(self, role: WorkspaceRole) -> TestClient:
        return make_workspace_client(
            self.app,
            user=self.users[role],
            workspace_id=self.workspace_id,
            role=role,
        )


ROLES = (
    WorkspaceRole.OWNER,
    WorkspaceRole.ADMIN,
    WorkspaceRole.EDITOR,
    WorkspaceRole.RUNNER,
    WorkspaceRole.VIEWER,
)

ENDPOINT_CASES = (
    EndpointCase("workspace view", "GET", "/matrix/workspace", frozenset(ROLES)),
    EndpointCase(
        "workspace update settings",
        "PATCH",
        "/matrix/workspace/settings",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
    EndpointCase(
        "workspace delete",
        "DELETE",
        "/matrix/workspace",
        frozenset({WorkspaceRole.OWNER}),
    ),
    EndpointCase(
        "workspace manage members",
        "POST",
        "/matrix/workspace/members",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
    EndpointCase("workflow view", "GET", "/matrix/workflows/seed", frozenset(ROLES)),
    EndpointCase(
        "workflow draft edit",
        "POST",
        "/matrix/workflows/seed/draft",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}),
    ),
    EndpointCase(
        "workflow publish",
        "POST",
        "/matrix/workflows/seed/publish",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
    EndpointCase(
        "workflow run",
        "POST",
        "/matrix/workflows/seed/run",
        frozenset(
            {
                WorkspaceRole.OWNER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
                WorkspaceRole.RUNNER,
            }
        ),
    ),
    EndpointCase("file view", "GET", "/matrix/files/file_1", frozenset(ROLES)),
    EndpointCase(
        "file upload",
        "POST",
        "/matrix/files",
        frozenset(
            {
                WorkspaceRole.OWNER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
                WorkspaceRole.RUNNER,
            }
        ),
    ),
    EndpointCase(
        "file delete",
        "DELETE",
        "/matrix/files/file_1",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}),
    ),
    EndpointCase("dataset view", "GET", "/matrix/test-sets/seed", frozenset(ROLES)),
    EndpointCase(
        "dataset create",
        "POST",
        "/matrix/test-sets",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}),
    ),
    EndpointCase(
        "document upload",
        "POST",
        "/matrix/test-sets/seed/documents/upload",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}),
    ),
    EndpointCase(
        "ground truth manage",
        "POST",
        "/matrix/test-sets/seed/documents/doc_1/ground-truth",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}),
    ),
    EndpointCase("run view", "GET", "/matrix/runs/run_1", frozenset(ROLES)),
    EndpointCase(
        "run cancel",
        "POST",
        "/matrix/runs/run_1/cancel",
        frozenset(
            {
                WorkspaceRole.OWNER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
                WorkspaceRole.RUNNER,
            }
        ),
    ),
    EndpointCase(
        "comparison refresh",
        "POST",
        "/matrix/evaluation-runs/run_1/results/result_1/comparison",
        frozenset(
            {
                WorkspaceRole.OWNER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
                WorkspaceRole.RUNNER,
            }
        ),
    ),
    EndpointCase("provider view", "GET", "/matrix/providers", frozenset(ROLES)),
    EndpointCase(
        "provider manage",
        "POST",
        "/matrix/providers",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
    EndpointCase(
        "provider use",
        "POST",
        "/matrix/providers/provider_1/use",
        frozenset(
            {
                WorkspaceRole.OWNER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
                WorkspaceRole.RUNNER,
            }
        ),
    ),
    EndpointCase(
        "api key manage",
        "POST",
        "/matrix/admin/api-keys",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
    EndpointCase(
        "api usage view",
        "GET",
        "/matrix/admin/workflows/wf_1/api-usage/summary",
        frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN}),
    ),
)


def _ok() -> dict[str, bool]:
    return {"ok": True}


def _build_matrix_app() -> FastAPI:
    router = APIRouter(prefix="/matrix", tags=["workspace-role-matrix"])

    router.add_api_route(
        "/workspace",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("workspace.view"))],
    )
    router.add_api_route(
        "/workspace/settings",
        _ok,
        methods=["PATCH"],
        dependencies=[Depends(require_workspace_capability("workspace.update_settings"))],
    )
    router.add_api_route(
        "/workspace",
        _ok,
        methods=["DELETE"],
        dependencies=[Depends(require_workspace_capability("workspace.delete"))],
    )
    router.add_api_route(
        "/workspace/members",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("workspace.manage_members"))],
    )
    router.add_api_route(
        "/workflows/seed",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("workflow.view"))],
    )
    router.add_api_route(
        "/workflows/seed/draft",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("workflow.edit_draft"))],
    )
    router.add_api_route(
        "/workflows/seed/publish",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("workflow.publish"))],
    )
    router.add_api_route(
        "/workflows/seed/run",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("workflow.run"))],
    )
    router.add_api_route(
        "/files/file_1",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("file.view"))],
    )
    router.add_api_route(
        "/files",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("file.upload"))],
    )
    router.add_api_route(
        "/files/file_1",
        _ok,
        methods=["DELETE"],
        dependencies=[Depends(require_workspace_capability("file.delete"))],
    )
    router.add_api_route(
        "/test-sets/seed",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("dataset.view"))],
    )
    router.add_api_route(
        "/test-sets",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("dataset.create"))],
    )
    router.add_api_route(
        "/test-sets/seed/documents/upload",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("document.upload"))],
    )
    router.add_api_route(
        "/test-sets/seed/documents/doc_1/ground-truth",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("ground_truth.manage"))],
    )
    router.add_api_route(
        "/runs/run_1",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("run.view"))],
    )
    router.add_api_route(
        "/runs/run_1/cancel",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("run.cancel"))],
    )
    router.add_api_route(
        "/evaluation-runs/run_1/results/result_1/comparison",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("comparison.refresh"))],
    )
    router.add_api_route(
        "/providers",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("provider.view"))],
    )
    router.add_api_route(
        "/providers",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("provider.manage"))],
    )
    router.add_api_route(
        "/providers/provider_1/use",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("provider.use"))],
    )
    router.add_api_route(
        "/admin/api-keys",
        _ok,
        methods=["POST"],
        dependencies=[Depends(require_workspace_capability("api_key.manage"))],
    )
    router.add_api_route(
        "/admin/workflows/wf_1/api-usage/summary",
        _ok,
        methods=["GET"],
        dependencies=[Depends(require_workspace_capability("api_usage.view"))],
    )

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def workspace_role_matrix_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[WorkspaceRoleMatrixHarness]:
    enable_rbac(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workspace-role-matrix.sqlite3'}"
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
        for role in ROLES[1:]:
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

    app = _build_matrix_app()
    yield WorkspaceRoleMatrixHarness(
        app=app,
        workspace_id=workspace_id,
        users=users,
        session_factory=session_factory,
    )
    app.dependency_overrides.clear()


def _request(client: TestClient, case: EndpointCase):
    match case.method:
        case "GET":
            return client.get(case.path)
        case "POST":
            return client.post(case.path)
        case "PATCH":
            return client.patch(case.path)
        case "DELETE":
            return client.delete(case.path)
        case _:
            raise AssertionError(f"Unsupported method: {case.method}")


@pytest.mark.parametrize("case", ENDPOINT_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("role", ROLES, ids=lambda role: role.value)
def test_workspace_role_matrix_matches_capability_policy(
    workspace_role_matrix_harness: WorkspaceRoleMatrixHarness,
    role: WorkspaceRole,
    case: EndpointCase,
) -> None:
    with workspace_role_matrix_harness.client(role) as client:
        response = _request(client, case)

    expected_status = 200 if role in case.allowed_roles else 403
    assert response.status_code == expected_status
