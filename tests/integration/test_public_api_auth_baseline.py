from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin.api_keys import router as admin_api_keys_router
from app.api.auth import get_authenticated_context
from app.api.public.error_response import PublicApiError, public_api_exception_handler
from app.api.public.router import router as public_router
from app.config import get_settings
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.repositories.api_key_repository import ApiKeyRecord
from app.repositories.task_run_repository import TaskRunSnapshot
from app.services.api_key_service import ApiKeyService, VerifiedApiKey
from app.services.workspace_access import ResolvedContext
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole

TEST_WORKFLOW_ID = "wf_test"
TEST_OTHER_WORKFLOW_ID = "wf_other"
TEST_WORKSPACE_ID = "ws_test"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _WorkflowDefinition:
    def __init__(self, nodes: list[object]) -> None:
        self.nodes = nodes

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {"nodes": []}


class _Workflow:
    def __init__(
        self,
        definition: _WorkflowDefinition,
        published_version: int | None,
        workspace_id: str | None = None,
    ) -> None:
        self.definition = definition
        self.published_version = published_version
        self.workspace_id = workspace_id


class _WorkflowStore:
    def __init__(self, *, workspace_id: str | None = None) -> None:
        self._workflows = {
            TEST_WORKFLOW_ID: _Workflow(
                _WorkflowDefinition(nodes=[]),
                published_version=1,
                workspace_id=workspace_id,
            ),
            TEST_OTHER_WORKFLOW_ID: _Workflow(
                _WorkflowDefinition(nodes=[]),
                published_version=1,
                workspace_id="ws_other" if workspace_id is not None else None,
            ),
        }

    def get(self, workflow_id: str, *, workspace_id: str | None = None) -> _Workflow | None:
        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            return None
        if workspace_id is not None and workflow.workspace_id != workspace_id:
            return None
        return workflow


class _ApiKeyRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, ApiKeyRecord] = {}
        self._by_hash: dict[str, ApiKeyRecord] = {}

    async def create(
        self,
        *,
        id: str,
        key_hash: str,
        key_prefix: str,
        workflow_id: str,
        workspace_id: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> ApiKeyRecord:
        record = ApiKeyRecord(
            id=id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            workflow_id=workflow_id,
            description=description,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            is_active=True,
            last_used_at=None,
            workspace_id=workspace_id,
        )
        self._by_id[id] = record
        self._by_hash[key_hash] = record
        return record

    async def get_by_hash_for_auth(
        self,
        key_hash: str,
    ) -> ApiKeyRecord | None:
        return self._by_hash.get(key_hash)

    async def touch_last_used_for_auth(
        self,
        id: str,
        when: datetime,
    ) -> None:
        record = self._by_id.get(id)
        if record is None:
            return
        self._by_id[id] = ApiKeyRecord(
            id=record.id,
            key_hash=record.key_hash,
            key_prefix=record.key_prefix,
            workflow_id=record.workflow_id,
            description=record.description,
            created_by=record.created_by,
            created_at=record.created_at,
            expires_at=record.expires_at,
            is_active=record.is_active,
            last_used_at=when,
            workspace_id=record.workspace_id,
        )
        self._by_hash[record.key_hash] = self._by_id[id]

    async def set_active(
        self,
        id: str,
        is_active: bool,
        *,
        workspace_id: str | None = None,
    ) -> bool:
        record = self._by_id.get(id)
        if record is None:
            return False
        updated = ApiKeyRecord(
            id=record.id,
            key_hash=record.key_hash,
            key_prefix=record.key_prefix,
            workflow_id=record.workflow_id,
            description=record.description,
            created_by=record.created_by,
            created_at=record.created_at,
            expires_at=record.expires_at,
            is_active=is_active,
            last_used_at=record.last_used_at,
            workspace_id=record.workspace_id,
        )
        self._by_id[id] = updated
        self._by_hash[updated.key_hash] = updated
        return True

    async def get_by_id(self, id: str, *, workspace_id: str | None = None) -> ApiKeyRecord | None:
        record = self._by_id.get(id)
        if record is not None and (workspace_id is None or record.workspace_id == workspace_id):
            return record
        return None

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        workspace_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[ApiKeyRecord]:
        records = [
            record
            for record in self._by_id.values()
            if (workspace_id is None or record.workspace_id == workspace_id)
            and (include_inactive or record.is_active)
        ]
        return records[offset : offset + limit]

    async def count(
        self,
        *,
        workspace_id: str | None = None,
        include_inactive: bool = True,
    ) -> int:
        return len(
            [
                record
                for record in self._by_id.values()
                if (workspace_id is None or record.workspace_id == workspace_id)
                and (include_inactive or record.is_active)
            ]
        )

    async def list_by_workflow(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[ApiKeyRecord]:
        return [
            record
            for record in self._by_id.values()
            if record.workflow_id == workflow_id
            and (workspace_id is None or record.workspace_id == workspace_id)
        ]


class _TaskRunRepo:
    def __init__(self) -> None:
        self._snapshots: dict[str, TaskRunSnapshot] = {}

    async def upsert_snapshot(
        self,
        *,
        task_id: str,
        status: str,
        workflow_id: str | None,
        workflow_name: str | None,
        run_name: str | None = None,
        source: str | None = None,
        workspace_id: str | None = None,
        evaluation_run_id: str | None = None,
        created_at: datetime | None,
        completed_at: datetime | None,
        duration_ms: int | None,
        node_summary: dict[str, int] | None,
        result_preview: str | None,
        results: list[dict[str, object]] | None,
        error: str | None,
        dag_hash: str | None = None,
        input_files: list[dict[str, object]] | None = None,
        workflow: dict[str, object] | None = None,
        updated_at: datetime | None,
    ) -> None:
        self._snapshots[task_id] = TaskRunSnapshot(
            task_id=task_id,
            status=status,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            run_name=run_name,
            source=source,
            workspace_id=workspace_id,
            evaluation_run_id=evaluation_run_id,
            created_at=created_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            node_summary=node_summary,
            result_preview=result_preview,
            results=results,
            error=error,
            dag_hash=dag_hash,
            input_files=input_files,
            workflow=workflow,
            updated_at=updated_at,
        )

    async def get_snapshot(
        self,
        workflow_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> TaskRunSnapshot | None:
        snapshot = self._snapshots.get(workflow_run_id)
        if snapshot is None:
            return None
        snapshot_workspace_id = getattr(snapshot, "workspace_id", None)
        if workspace_id is not None and snapshot_workspace_id != workspace_id:
            return None
        return snapshot

    async def list_snapshots(
        self,
        *,
        workflow_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRunSnapshot]:
        snapshots = list(self._snapshots.values())
        if workflow_id is not None:
            snapshots = [snapshot for snapshot in snapshots if snapshot.workflow_id == workflow_id]
        if workspace_id is not None:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if getattr(snapshot, "workspace_id", None) == workspace_id
            ]
        return sorted(
            snapshots,
            key=lambda snapshot: snapshot.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )


class _UploadHandler:
    async def receive_upload(self, file_part: object, run_id: str) -> str:
        filename = getattr(file_part, "filename", None) or "upload"
        return f"/app/storage/tasks/{run_id}/original/{filename}"


def _build_app(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _ApiKeyRepo, _TaskRunRepo]:
    app = FastAPI()
    app.include_router(admin_api_keys_router)
    app.include_router(public_router)
    app.add_exception_handler(PublicApiError, cast(Any, public_api_exception_handler))

    api_key_repo = _ApiKeyRepo()
    api_key_service = ApiKeyService(repository=cast(Any, api_key_repo))
    workflow_store = _WorkflowStore(workspace_id=TEST_WORKSPACE_ID)
    task_run_repo = _TaskRunRepo()

    app.state.api_key_service = api_key_service
    app.state.dag_scheduler = SimpleNamespace()
    app.state.engine_client = SimpleNamespace()
    app.state.event_store = SimpleNamespace()
    app.state.running_tasks = {}
    app.state.auth_resolver = None
    app.state.provider_store = None

    admin_ctx = AuthenticatedContext(
        user=AuthUser(id="admin_1", email="admin@example.com", name="Admin"),
        session=AuthSessionInfo(
            id="sess_admin_1", user_id="admin_1", expires_at=datetime.now(timezone.utc)
        ),
        workspace_id=TEST_WORKSPACE_ID,
        role=WorkspaceRole.OWNER,
        capabilities=CAPABILITIES[WorkspaceRole.OWNER],
    )

    async def _admin_context() -> AuthenticatedContext:
        return admin_ctx

    app.dependency_overrides[get_authenticated_context] = _admin_context

    resolved_admin = ResolvedContext(
        user=admin_ctx.user,
        session=admin_ctx.session,
        workspace_id=TEST_WORKSPACE_ID,
        role=WorkspaceRole.OWNER,
        capabilities=CAPABILITIES[WorkspaceRole.OWNER],
    )

    import app.api.admin.api_keys as admin_api_keys_module
    import app.api.public.workflow_runs as public_workflow_runs_module

    monkeypatch.setattr(
        admin_api_keys_module,
        "_resolve_workflow",
        lambda workflow_id, workspace_id=None: (
            admin_api_keys_module._ResolvedWorkflow(
                id=workflow_id,
                workspace_id=workflow.workspace_id,
            )
            if (workflow := workflow_store.get(workflow_id, workspace_id=workspace_id)) is not None
            else None
        ),
    )
    monkeypatch.setattr(
        admin_api_keys_module,
        "_resolve_api_key_context",
        lambda _request, _context: resolved_admin,
    )
    monkeypatch.setattr(public_workflow_runs_module, "get_workflow_store", lambda: workflow_store)
    monkeypatch.setattr(public_workflow_runs_module, "TaskRunRepository", lambda: task_run_repo)
    monkeypatch.setattr(public_workflow_runs_module, "_start_dag_run", lambda **_kwargs: None)
    monkeypatch.setattr(public_workflow_runs_module, "UploadHandler", _UploadHandler)

    async def _await_run_terminal(
        workflow_run_id: str,
        timeout: float,
        *,
        workspace_id: str | None = None,
    ) -> TaskRunSnapshot:
        snapshot = TaskRunSnapshot(
            task_id=workflow_run_id,
            status="completed",
            workflow_id=TEST_WORKFLOW_ID,
            workspace_id=workspace_id,
            results=[{"content": "done"}],
            duration_ms=42,
            node_summary={"n1": 1},
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        task_run_repo._snapshots[workflow_run_id] = snapshot
        return snapshot

    monkeypatch.setattr(public_workflow_runs_module, "await_run_terminal", _await_run_terminal)

    client = TestClient(app)
    return client, api_key_repo, task_run_repo


def _issue_key(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/admin/api-keys",
        json={"workflow_id": TEST_WORKFLOW_ID, "description": "baseline key"},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload["id"], payload["key"]


def test_public_api_auth_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'public-api-auth.sqlite3'}")
    client, _api_key_repo, _task_run_repo = _build_app(monkeypatch)
    key_id, full_key = _issue_key(client)

    run_response = client.post(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"inputs": {}},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    workflow_run_id = run_payload["workflow_run_id"]
    assert run_payload["status"] == "succeeded"

    upload_response = client.post(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
        headers={"Authorization": f"Bearer {full_key}"},
        files={"file": ("invoice.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    upload_run_id = upload_payload["workflow_run_id"]
    assert upload_payload["status"] == "succeeded"

    status_response = client.get(
        f"/api/v1/workflow-runs/{workflow_run_id}",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["workflow_id"] == TEST_WORKFLOW_ID

    results_response = client.get(
        f"/api/v1/workflow-runs/{workflow_run_id}/results",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert results_response.status_code == 200
    assert results_response.json()["workflow_run_id"] == workflow_run_id

    history_response = client.get(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/runs",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert history_payload["meta"]["total"] >= 2
    assert {item["workflow_run_id"] for item in history_payload["data"]} >= {
        workflow_run_id,
        upload_run_id,
    }

    mismatch_response = client.post(
        f"/api/v1/workflows/{TEST_OTHER_WORKFLOW_ID}/run",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"inputs": {}},
    )
    assert mismatch_response.status_code == 403
    assert mismatch_response.json()["error"]["code"] == "WORKFLOW_MISMATCH"

    revoked_response = client.post(
        f"/api/admin/api-keys/{key_id}/revoke",
        headers={"Authorization": "Bearer admin-session"},
    )
    assert revoked_response.status_code == 200

    revoked_key_response = client.post(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"inputs": {}},
    )
    assert revoked_key_response.status_code == 401
    assert revoked_key_response.json()["error"]["code"] == "INVALID_API_KEY"

    missing_auth_response = client.get(f"/api/v1/workflow-runs/{workflow_run_id}")
    assert missing_auth_response.status_code == 401
    assert missing_auth_response.json()["error"]["code"] == "UNAUTHORIZED"

    malformed_auth_response = client.get(
        f"/api/v1/workflow-runs/{workflow_run_id}",
        headers={"Authorization": "Basic nope"},
    )
    assert malformed_auth_response.status_code == 401
    assert malformed_auth_response.json()["error"]["code"] == "UNAUTHORIZED"


def test_public_api_enforced_uses_key_bound_workspace_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'public-api-rbac.sqlite3'}")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(public_router)
    app.add_exception_handler(PublicApiError, cast(Any, public_api_exception_handler))

    workflow_store = _WorkflowStore(workspace_id="ws_public")
    task_run_repo = _TaskRunRepo()

    class _StaticApiKeyService:
        async def verify(self, _token: str) -> VerifiedApiKey:
            return VerifiedApiKey(
                id="key_public",
                workflow_id=TEST_WORKFLOW_ID,
                key_prefix="dca_public",
                workspace_id="ws_public",
            )

    app.state.api_key_service = _StaticApiKeyService()
    app.state.dag_scheduler = SimpleNamespace()
    app.state.engine_client = SimpleNamespace()
    app.state.event_store = SimpleNamespace()
    app.state.running_tasks = {}
    app.state.auth_resolver = None
    app.state.provider_store = None

    import app.api.public.workflow_runs as public_workflow_runs_module

    recorded_workspace_ids: list[str | None] = []

    class _UsageService:
        async def record_invocation(self, **kwargs: Any) -> None:
            recorded_workspace_ids.append(kwargs.get("workspace_id"))

        def task_storage_bytes(self, _task_id: str | None) -> int:
            return 0

    monkeypatch.setattr(public_workflow_runs_module, "get_workflow_store", lambda: workflow_store)
    monkeypatch.setattr(public_workflow_runs_module, "TaskRunRepository", lambda: task_run_repo)
    monkeypatch.setattr(public_workflow_runs_module, "ApiUsageService", _UsageService)
    started_runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        public_workflow_runs_module,
        "_start_dag_run",
        lambda **kwargs: started_runs.append(kwargs),
    )

    async def _await_run_terminal(
        workflow_run_id: str,
        timeout: float,
        *,
        workspace_id: str | None = None,
    ) -> TaskRunSnapshot:
        snapshot = TaskRunSnapshot(
            task_id=workflow_run_id,
            status="completed",
            workflow_id=TEST_WORKFLOW_ID,
            workspace_id=workspace_id,
            results=[{"content": "done"}],
            duration_ms=42,
            node_summary={"n1": 1},
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        task_run_repo._snapshots[workflow_run_id] = snapshot
        return snapshot

    monkeypatch.setattr(public_workflow_runs_module, "await_run_terminal", _await_run_terminal)

    client = TestClient(app)
    run_response = client.post(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
        headers={"Authorization": "Bearer dca_public"},
        json={"inputs": {}},
    )
    assert run_response.status_code == 200
    assert started_runs[0]["workspace_id"] == "ws_public"
    assert recorded_workspace_ids == ["ws_public"]
    workflow_run_id = run_response.json()["workflow_run_id"]

    status_response = client.get(
        f"/api/v1/workflow-runs/{workflow_run_id}",
        headers={"Authorization": "Bearer dca_public"},
    )
    assert status_response.status_code == 200

    task_run_repo._snapshots["task_cross"] = TaskRunSnapshot(
        task_id="task_cross",
        status="completed",
        workflow_id=TEST_WORKFLOW_ID,
        workspace_id="ws_other",
        results=[{"content": "leak"}],
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    cross_status_response = client.get(
        "/api/v1/workflow-runs/task_cross",
        headers={"Authorization": "Bearer dca_public"},
    )
    assert cross_status_response.status_code == 404

    history_response = client.get(
        f"/api/v1/workflows/{TEST_WORKFLOW_ID}/runs",
        headers={"Authorization": "Bearer dca_public"},
    )
    assert history_response.status_code == 200
    returned_ids = {item["workflow_run_id"] for item in history_response.json()["data"]}
    assert workflow_run_id in returned_ids
    assert "task_cross" not in returned_ids
