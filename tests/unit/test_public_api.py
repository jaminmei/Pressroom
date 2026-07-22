"""Unit tests for the public API surface (/api/v1/*).

Mounts ONLY the public router on a minimal FastAPI app and stubs ``app.state``
services via MagicMock — avoids importing the full app (sqlalchemy / workflow
runtime). Mirrors the pattern in ``tests/unit/test_engines_api.py``.

Covers the 6 spec requirements and all auth/run/query scenarios from the
public API forwarding behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.public.error_response import PublicApiError, public_api_exception_handler
from app.api.public.router import router as public_router
from app.api.public.workflow_runs import await_run_terminal
from app.repositories.task_run_repository import TaskRunSnapshot
from app.services.api_key_service import ApiKeyVerificationError, VerifiedApiKey

TEST_KEY = "dca_test_key"
TEST_WORKFLOW_ID = "wf_test"
TEST_WORKSPACE_ID = "ws_test"
NOW = datetime.now(timezone.utc)


def _build_app(
    *,
    workflow_store: MagicMock | None = None,
    snapshot: TaskRunSnapshot | None = None,
    snapshots: list[TaskRunSnapshot] | None = None,
) -> FastAPI:
    """Construct an isolated FastAPI app with public router + mocked state.

    ``snapshot`` / ``snapshots`` drive the canned TaskRunRepository responses.
    """
    app = FastAPI()
    app.include_router(public_router)
    app.add_exception_handler(PublicApiError, public_api_exception_handler)

    api_key_service = MagicMock()

    async def _verify(key: str):  # type: ignore[no-untyped-def]
        if key == TEST_KEY:
            return VerifiedApiKey(
                id="key1",
                workflow_id=TEST_WORKFLOW_ID,
                key_prefix="dca_test",
                workspace_id=TEST_WORKSPACE_ID,
            )
        raise ApiKeyVerificationError("invalid")

    api_key_service.verify = _verify

    app.state.api_key_service = api_key_service
    # Stubbed downstream services — only touched by _start_dag_run (mocked out).
    app.state.dag_scheduler = MagicMock()
    app.state.engine_client = MagicMock()
    app.state.event_store = MagicMock()
    app.state.running_tasks = {}
    app.state.auth_resolver = MagicMock()
    app.state.provider_store = MagicMock()

    # Mock the workflow store + TaskRunRepository before app creation so each
    # test gets an isolated fixture.
    wf_store = workflow_store or _default_workflow_store()
    app.state._workflow_store = wf_store  # noqa: SLN001 - test hook
    app.state._snapshot = snapshot  # noqa: SLN001 - test hook
    app.state._snapshots = snapshots  # noqa: SLN001 - test hook
    return app


def _default_workflow_store() -> MagicMock:
    store = MagicMock()
    wf = SimpleNamespace(
        definition=SimpleNamespace(nodes=[]),
        published_version=1,
    )
    store.get = MagicMock(return_value=wf)
    return store


def _patch_repos(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    """Patch the repo-constructing call sites to read from app.state fixtures."""
    workflow_store = app.state._workflow_store
    snapshot = app.state._snapshot
    snapshots = app.state._snapshots

    monkeypatch.setattr(
        "app.api.public.workflow_runs.get_workflow_store",
        lambda: workflow_store,
    )
    monkeypatch.setattr(
        "app.api.public.workflow_runs._start_dag_run",
        lambda **kw: None,
    )

    # Patch TaskRunRepository so its async methods return the canned fixtures.
    real_repo_cls = pytest.importorskip("app.api.public.workflow_runs").TaskRunRepository

    class _StubRepo:
        async def get_snapshot(
            self,
            workflow_run_id: str,
            *,
            workspace_id: str | None = None,
        ) -> TaskRunSnapshot | None:
            assert workspace_id == TEST_WORKSPACE_ID
            return snapshot

        async def list_snapshots(self, **kw):  # type: ignore[no-untyped-def]
            assert kw["workspace_id"] == TEST_WORKSPACE_ID
            return snapshots or []

    monkeypatch.setattr("app.api.public.workflow_runs.TaskRunRepository", _StubRepo)
    # Silence unused-import lint warning for real_repo_cls.
    del real_repo_cls


def _client_for(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workflow_store: MagicMock | None = None,
    snapshot: TaskRunSnapshot | None = None,
    snapshots: list[TaskRunSnapshot] | None = None,
) -> TestClient:
    app = _build_app(
        workflow_store=workflow_store,
        snapshot=snapshot,
        snapshots=snapshots,
    )
    _patch_repos(monkeypatch, app)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Auth scenarios
# ---------------------------------------------------------------------------


class TestAuth:
    def test_health_no_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_missing_authorization_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch)
        resp = client.get("/api/v1/workflow-runs/run_1")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch)
        resp = client.get(
            "/api/v1/workflow-runs/run_1",
            headers={"Authorization": "Bearer dca_wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_API_KEY"

    def test_workflow_mismatch_on_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch)
        resp = client.post(
            "/api/v1/workflows/wf_other/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {}},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "WORKFLOW_MISMATCH"

    def test_list_history_workflow_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch)
        resp = client.get(
            "/api/v1/workflows/wf_other/runs",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "WORKFLOW_MISMATCH"


# ---------------------------------------------------------------------------
# Run scenarios
# ---------------------------------------------------------------------------


class TestRunWorkflow:
    def test_run_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snap = TaskRunSnapshot(
            task_id="task_abc",
            workflow_id=TEST_WORKFLOW_ID,
            workspace_id=TEST_WORKSPACE_ID,
            status="completed",
            results=[{"content": "hello"}],
            duration_ms=42,
            node_summary={"n1": 1},
            created_at=NOW,
            completed_at=NOW,
        )
        client = _client_for(monkeypatch, snapshot=snap)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {"file": "https://example.com/x.pdf"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "succeeded"
        assert body["outputs"]["text"] == "hello"
        assert body["workflow_run_id"].startswith("task_")

    def test_run_workflow_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        empty_store = MagicMock()
        empty_store.get = MagicMock(return_value=None)
        client = _client_for(monkeypatch, workflow_store=empty_store)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {}},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"

    def test_run_workflow_not_published(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = SimpleNamespace(
            definition=SimpleNamespace(nodes=[]),
            published_version=None,
        )
        store = MagicMock()
        store.get = MagicMock(return_value=wf)
        client = _client_for(monkeypatch, workflow_store=store)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {}},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "WORKFLOW_NOT_PUBLISHED"

    def test_run_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _timeout(*a, **kw):  # type: ignore[no-untyped-def]
            raise PublicApiError(
                status_code=504,
                code="RUN_TIMEOUT",
                message="timeout",
                workflow_run_id="x",
            )

        monkeypatch.setattr("app.api.public.workflow_runs.await_run_terminal", _timeout)
        client = _client_for(monkeypatch)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {}},
        )
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "RUN_TIMEOUT"


# ---------------------------------------------------------------------------
# Query scenarios
# ---------------------------------------------------------------------------


class TestQueries:
    def _owned_snap(self, **overrides) -> TaskRunSnapshot:  # type: ignore[no-untyped-def]
        defaults = dict(
            task_id="run_1",
            workflow_id=TEST_WORKFLOW_ID,
            workspace_id=TEST_WORKSPACE_ID,
            status="completed",
            results=[{"content": "done"}],
            duration_ms=10,
            node_summary={"n": 1},
            created_at=NOW,
            completed_at=NOW,
        )
        defaults.update(overrides)
        return TaskRunSnapshot(**defaults)  # type: ignore[arg-type]

    def test_get_status_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snap = self._owned_snap()
        client = _client_for(monkeypatch, snapshot=snap)
        resp = client.get(
            "/api/v1/workflow-runs/run_1",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # 7 fields per spec.
        assert set(body) == {
            "workflow_run_id",
            "workflow_id",
            "status",
            "elapsed_time_ms",
            "total_steps",
            "created_at",
            "finished_at",
        }
        assert body["workflow_id"] == TEST_WORKFLOW_ID

    def test_get_status_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client_for(monkeypatch, snapshot=None)
        resp = client.get(
            "/api/v1/workflow-runs/missing",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RUN_NOT_FOUND"

    def test_get_status_not_owned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snap = self._owned_snap(workflow_id="wf_someone_else")
        client = _client_for(monkeypatch, snapshot=snap)
        resp = client.get(
            "/api/v1/workflow-runs/run_1",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "RUN_NOT_OWNED"

    def test_get_results_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snap = self._owned_snap()
        client = _client_for(monkeypatch, snapshot=snap)
        resp = client.get(
            "/api/v1/workflow-runs/run_1/results",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_run_id"] == "run_1"
        assert body["status"] == "succeeded"
        assert body["results"] == [{"content": "done"}]

    def test_get_results_not_complete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snap = self._owned_snap(status="running")
        client = _client_for(monkeypatch, snapshot=snap)
        resp = client.get(
            "/api/v1/workflow-runs/run_1/results",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RUN_NOT_COMPLETE"

    def test_list_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snaps = [self._owned_snap(task_id=f"r{i}", status="completed") for i in range(3)]
        client = _client_for(monkeypatch, snapshots=snaps)
        resp = client.get(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/runs?page=1&limit=2",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["meta"]["total"] == 3
        assert body["meta"]["page"] == 1
        assert body["meta"]["limit"] == 2


# ---------------------------------------------------------------------------
# await_run_terminal — direct timeout/success checks (used internally)
# ---------------------------------------------------------------------------


def test_await_run_terminal_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NeverRepo:
        async def get_snapshot(
            self, task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot | None:
            return None

    monkeypatch.setattr("app.api.public.workflow_runs.TaskRunRepository", _NeverRepo)
    import asyncio

    with pytest.raises(PublicApiError) as exc_info:
        asyncio.run(await_run_terminal("r", timeout=0.1, workspace_id=TEST_WORKSPACE_ID))
    assert exc_info.value.code == "RUN_TIMEOUT"
    assert exc_info.value.status_code == 504
