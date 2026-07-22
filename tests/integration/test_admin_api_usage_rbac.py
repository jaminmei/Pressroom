from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin.api_usage import router as admin_api_usage_router
from app.api.workflows import get_workflow_store
from app.db import session as db_session
from app.db.base import Base
from app.models.auth import AuthUser
from app.models.db.api_invocation import ApiInvocation
from app.models.db.task_run import TaskRun
from app.models.db.workflow_record import WorkflowRecord
from app.services.api_usage_service import ApiUsageService
from app.services.workspace_permissions import WorkspaceRole
from tests._workspace_fixture import (
    disable_rbac,
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
    get_workflow_store.cache_clear()


@dataclass(frozen=True, slots=True)
class ApiUsageHarness:
    owner_client: TestClient
    editor_client: TestClient
    owner_workspace_id: str
    workflow_id: str
    other_workflow_id: str
    workflow_run_id: str


@pytest.fixture()
def api_usage_harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[ApiUsageHarness]:
    enable_rbac(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'admin-api-usage-rbac.sqlite3'}"
    )
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    owner_app = FastAPI()
    owner_app.include_router(admin_api_usage_router)
    editor_app = FastAPI()
    editor_app.include_router(admin_api_usage_router)

    session_factory = db_session.SessionLocal
    owner_user_id = make_user(session_factory, "owner@example.com")
    owner_workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=owner_user_id,
        member_role=WorkspaceRole.OWNER,
    )
    editor_user_id = make_user(session_factory, "editor@example.com")
    with session_factory() as session:
        from app.models.db.workspace_member import WorkspaceMember

        session.add(
            WorkspaceMember(
                id="wsm_editor_owner_usage",
                workspace_id=owner_workspace_id,
                user_id=editor_user_id,
                role=WorkspaceRole.EDITOR.value,
            )
        )
        session.commit()
    other_owner_id = make_user(session_factory, "other-owner@example.com")
    other_workspace_id = make_workspace_with_member(
        session_factory,
        owner_user_id=other_owner_id,
        member_role=WorkspaceRole.OWNER,
    )
    with session_factory() as session:
        from app.models.db.workspace_member import WorkspaceMember

        session.add(
            WorkspaceMember(
                id="wsm_owner_other_usage",
                workspace_id=other_workspace_id,
                user_id=owner_user_id,
                role=WorkspaceRole.OWNER.value,
            )
        )
        session.commit()

    owner_client = make_workspace_client(
        owner_app,
        user=AuthUser(id=owner_user_id, email="owner@example.com"),
        workspace_id=owner_workspace_id,
        role=WorkspaceRole.OWNER,
    )
    editor_client = make_workspace_client(
        editor_app,
        user=AuthUser(id=editor_user_id, email="editor@example.com"),
        workspace_id=owner_workspace_id,
        role=WorkspaceRole.EDITOR,
    )

    workflow_id = "wf_owner_usage"
    other_workflow_id = "wf_other_usage"
    workflow_run_id = "task_owner_usage"

    with session_factory() as session:
        session.add(
            WorkflowRecord(
                id=workflow_id,
                workflow_key="wk_owner_usage",
                name="Owner workflow",
                description=None,
                workspace_id=owner_workspace_id,
                current_definition_json={"nodes": [], "connections": []},
                latest_version=1,
                published_version=1,
                created_by_user_id=owner_user_id,
                last_saved_by_user_id=owner_user_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            WorkflowRecord(
                id=other_workflow_id,
                workflow_key="wk_other_usage",
                name="Other workflow",
                description=None,
                workspace_id=other_workspace_id,
                current_definition_json={"nodes": [], "connections": []},
                latest_version=1,
                published_version=1,
                created_by_user_id=other_owner_id,
                last_saved_by_user_id=other_owner_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            TaskRun(
                id=workflow_run_id,
                status="completed",
                workflow_id=workflow_id,
                workflow_name="Owner workflow",
                run_name="Owner usage run",
                source="api_forward",
                workspace_id=owner_workspace_id,
                evaluation_run_id=None,
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                duration_ms=120,
                node_summary_json='{"total": 1, "completed": 1, "failed": 0}',
                result_preview="preview",
                results_json='[{"content": "ok"}]',
                error=None,
                dag_hash=None,
                input_files_json=None,
                workflow_json='{"nodes": [], "connections": []}',
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            ApiInvocation(
                id="api_inv_owner_usage",
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
                api_key_id="key_owner_usage",
                api_key_prefix="dca_owner",
                endpoint_kind="json_run",
                http_status=200,
                workflow_status="completed",
                response_time_ms=120,
                input_metadata_json='{"input": "value"}',
                error_json=None,
                storage_bytes=10,
                created_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    yield ApiUsageHarness(
        owner_client=owner_client,
        editor_client=editor_client,
        owner_workspace_id=owner_workspace_id,
        workflow_id=workflow_id,
        other_workflow_id=other_workflow_id,
        workflow_run_id=workflow_run_id,
    )

    owner_app.dependency_overrides.clear()
    editor_app.dependency_overrides.clear()
    get_workflow_store.cache_clear()


@pytest.mark.parametrize("runtime_role", ["backend", "worker"])
def test_public_runtime_rejects_api_usage_flag_off(
    monkeypatch: pytest.MonkeyPatch,
    runtime_role: str,
) -> None:
    from typing import cast

    from app.config import RuntimeRole, WorkspaceRuntimeEnvError, require_workspace_runtime_env

    disable_rbac(monkeypatch)

    with pytest.raises(
        WorkspaceRuntimeEnvError,
        match="public deployments require workspace RBAC enforcement",
    ):
        require_workspace_runtime_env(cast(RuntimeRole, runtime_role))


def test_owner_can_read_api_usage_summary_runs_and_trace(
    api_usage_harness: ApiUsageHarness,
) -> None:
    owner = api_usage_harness.owner_client

    summary = owner.get(f"/api/admin/workflows/{api_usage_harness.workflow_id}/api-usage/summary")
    runs = owner.get(f"/api/admin/workflows/{api_usage_harness.workflow_id}/api-usage/runs")
    trace = owner.get(
        f"/api/admin/workflows/{api_usage_harness.workflow_id}/api-usage/runs/{api_usage_harness.workflow_run_id}/trace"
    )

    assert summary.status_code == 200
    assert runs.status_code == 200
    assert trace.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/workflows/{workflow_id}/api-usage/summary",
        "/api/admin/workflows/{workflow_id}/api-usage/runs",
        "/api/admin/workflows/{workflow_id}/api-usage/runs/{workflow_run_id}/trace",
    ],
)
def test_editor_cannot_read_api_usage(
    api_usage_harness: ApiUsageHarness,
    path: str,
) -> None:
    response = api_usage_harness.editor_client.get(
        path.format(
            workflow_id=api_usage_harness.workflow_id,
            workflow_run_id=api_usage_harness.workflow_run_id,
        )
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "api_usage.view required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/workflows/{workflow_id}/api-usage/summary",
        "/api/admin/workflows/{workflow_id}/api-usage/runs",
        "/api/admin/workflows/{workflow_id}/api-usage/runs/{workflow_run_id}/trace",
    ],
)
def test_cross_workspace_api_usage_returns_404(
    api_usage_harness: ApiUsageHarness,
    path: str,
) -> None:
    response = api_usage_harness.owner_client.get(
        path.format(
            workflow_id=api_usage_harness.other_workflow_id,
            workflow_run_id=api_usage_harness.workflow_run_id,
        )
    )

    assert response.status_code == 404


@pytest.mark.asyncio()
async def test_retention_rejects_null_workspace_when_rbac_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_rbac(monkeypatch)

    with pytest.raises(RuntimeError, match="workspace_id required"):
        await ApiUsageService().enforce_retention(
            workflow_id="wf_usage",
            workspace_id=None,
            exclude_invocation_id="api_inv_current",
        )
