"""API-level tests for the public /run/upload multipart endpoint.

Covers public upload behavior:
  - Happy path: multipart PDF upload → 200 succeeded with outputs
  - Auth errors (401/403/404)
  - Input validation (oversized, missing file, two files, malformed options,
    magic byte mismatch)
  - Regression: /run JSON endpoint still returns the same envelope shape
  - DAG-not-started on input failures

Mirrors the TestClient + monkeypatch pattern from tests/unit/test_public_api.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.public.error_response import PublicApiError, public_api_exception_handler
from app.api.public.router import router as public_router
from app.repositories.task_run_repository import TaskRunSnapshot
from app.services.api_key_service import ApiKeyVerificationError, VerifiedApiKey
from app.services.upload_handler import UploadHandlerError

TEST_KEY = "dca_test_key"
TEST_WORKFLOW_ID = "wf_test"
TEST_WORKSPACE_ID = "ws_test"
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    """Construct an isolated FastAPI app with public router + stubbed state."""
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

    # Stubbed downstream services.
    app.state.dag_scheduler = MagicMock()
    app.state.engine_client = MagicMock()
    app.state.event_store = MagicMock()
    app.state.running_tasks = {}
    app.state.auth_resolver = MagicMock()
    app.state.provider_store = MagicMock()

    return app


def _patch_all(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_bytes: int = 20_000_000,
    upload_return: str | None = None,
    upload_error: UploadHandlerError | None = None,
    mock_rate_limiter: bool = True,
    rate_limit_per_minute: int = 10,
) -> MagicMock:
    """Set up all monkeypatches for the /run/upload endpoint.

    When ``mock_rate_limiter=True`` (default), ``RateLimiter.check`` is
    patched to a no-op.  When False, the RateLimiter constructor is patched
    to return a shared singleton so rate state persists across requests.

    Returns the mocked ``_start_dag_run`` so tests can assert call/not-called.
    """
    # ---- workflow store ----
    wf_store = MagicMock()
    wf = SimpleNamespace(
        definition=SimpleNamespace(
            nodes=[
                SimpleNamespace(id="input_1", type="input/file", config={"file": "$file_0"}),
            ]
        ),
        published_version=1,
    )
    wf_store.get = MagicMock(return_value=wf)
    monkeypatch.setattr("app.api.public.workflow_runs.get_workflow_store", lambda: wf_store)

    # ---- _start_dag_run (tracked for assertion) ----
    start_mock = MagicMock()
    monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)

    # ---- await_run_terminal → completed snapshot ----
    async def _await_terminal(*a, **kw):  # type: ignore[no-untyped-def]
        return TaskRunSnapshot(
            task_id="task_abc",
            workflow_id=TEST_WORKFLOW_ID,
            workspace_id=TEST_WORKSPACE_ID,
            status="completed",
            results=[{"content": "extracted text"}],
            duration_ms=42,
            node_summary={"n1": 1},
            created_at=NOW,
            completed_at=NOW,
        )

    monkeypatch.setattr("app.api.public.workflow_runs.await_run_terminal", _await_terminal)

    if mock_rate_limiter:

        async def _rate_ok(self, key: str) -> None:  # type: ignore[no-untyped-def]
            return None

        monkeypatch.setattr("app.services.rate_limiter.RateLimiter.check", _rate_ok)
    else:
        from app.services.rate_limiter import RateLimiter as RealRateLimiter

        _shared_limiter = RealRateLimiter(rate_per_minute=rate_limit_per_minute)
        monkeypatch.setattr(
            "app.api.public.workflow_runs.RateLimiter",
            lambda *a, **kw: _shared_limiter,
        )

    # ---- UploadHandler.receive_upload ----
    uh = MagicMock()
    if upload_error is not None:
        uh.receive_upload = AsyncMock(side_effect=upload_error)
    else:
        uh.receive_upload = AsyncMock(
            return_value=upload_return or "/app/storage/tasks/task_abc/original/test.pdf"
        )
    monkeypatch.setattr("app.api.public.workflow_runs.UploadHandler", lambda: uh)

    # ---- get_settings (max_bytes ceiling + timeout) ----
    settings = SimpleNamespace(
        input_upload_max_bytes=max_bytes,
        workflow_api_timeout_seconds=300,
        input_upload_rate_limit_per_minute=10,
    )
    monkeypatch.setattr("app.api.public.workflow_runs.get_settings", lambda: settings)

    # ---- TaskRunRepository stub (get_snapshot + upsert_snapshot) ----
    class _StubRepo:
        async def get_snapshot(
            self, task_id: str, *, workspace_id: str | None = None
        ) -> TaskRunSnapshot | None:
            assert workspace_id == TEST_WORKSPACE_ID
            return None

        async def upsert_snapshot(self, **kw) -> None:  # type: ignore[no-untyped-def]
            return None

        async def list_snapshots(self, **kw) -> list:  # type: ignore[no-untyped-def]
            return []

    monkeypatch.setattr("app.api.public.workflow_runs.TaskRunRepository", _StubRepo)

    return start_mock


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_bytes: int = 20_000_000,
    upload_return: str | None = None,
    upload_error: UploadHandlerError | None = None,
    mock_rate_limiter: bool = True,
    rate_limit_per_minute: int = 10,
) -> TestClient:
    """Build and return a TestClient wired with all patches."""
    app = _build_app()
    _patch_all(
        monkeypatch,
        max_bytes=max_bytes,
        upload_return=upload_return,
        upload_error=upload_error,
        mock_rate_limiter=mock_rate_limiter,
        rate_limit_per_minute=rate_limit_per_minute,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestUploadWorkflow:
    """Tests for POST /api/v1/workflows/{workflow_id}/run/upload."""

    # -- 1. Happy path -------------------------------------------------------

    def test_upload_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("invoice.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "succeeded"
        assert body["workflow_run_id"].startswith("task_")
        assert body["outputs"]["text"] == "extracted text"
        assert body["outputs"]["results"] == [{"content": "extracted text"}]
        assert body["elapsed_time_ms"] == 42
        assert body["total_steps"] == 1
        assert "created_at" in body
        assert "finished_at" in body
        assert ".pdf" in body["inputs"]["file"]

    # -- 2. Missing API key --------------------------------------------------

    def test_missing_api_key_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    # -- 3. Wrong API key (workflow mismatch) --------------------------------

    def test_wrong_api_key_workflow_mismatch_returns_403(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(monkeypatch)
        resp = client.post(
            "/api/v1/workflows/wf_other/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "WORKFLOW_MISMATCH"

    # -- 4. Workflow not published -------------------------------------------

    def test_workflow_not_published_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        # Override workflow store: published_version is None.
        unpub_wf = SimpleNamespace(definition=SimpleNamespace(nodes=[]), published_version=None)
        store = MagicMock()
        store.get = MagicMock(return_value=unpub_wf)
        monkeypatch.setattr("app.api.public.workflow_runs.get_workflow_store", lambda: store)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "WORKFLOW_NOT_PUBLISHED"

    # -- 5. Workflow not found -----------------------------------------------

    def test_workflow_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        # Override workflow store: returns None.
        empty_store = MagicMock()
        empty_store.get = MagicMock(return_value=None)
        monkeypatch.setattr("app.api.public.workflow_runs.get_workflow_store", lambda: empty_store)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"

    # -- 6. Oversized Content-Length -----------------------------------------

    def test_oversized_content_length_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Set max_bytes to 5 so any real multipart body exceeds it.
        client = _client(monkeypatch, max_bytes=5)
        from app.api.public.workflow_runs import _start_dag_run as orig_start

        monkeypatch.setattr(
            "app.api.public.workflow_runs._start_dag_run",
            MagicMock(wraps=orig_start),
        )
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)

        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("big.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "exceeds limit" in resp.json()["error"]["message"]
        # DAG must NOT be started on input failure.
        start_mock.assert_not_called()

    # -- 7. Missing file part ------------------------------------------------

    def test_missing_file_part_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)
        # Send multipart with no "file" field.
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            data={"something": "else"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "Missing 'file' part" in resp.json()["error"]["message"]
        start_mock.assert_not_called()

    # -- 8. Two file parts ---------------------------------------------------

    def test_two_file_parts_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files=[
                ("file", ("a.pdf", b"%PDF-1.4", "application/pdf")),
                ("file", ("b.pdf", b"%PDF-1.4", "application/pdf")),
            ],
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "Only one 'file' part allowed" in resp.json()["error"]["message"]
        start_mock.assert_not_called()

    # -- 9. Malformed options JSON -------------------------------------------

    def test_malformed_options_json_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("ok.pdf", b"%PDF-1.4", "application/pdf")},
            data={"options": "this is not json {{{"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "Malformed options JSON" in resp.json()["error"]["message"]
        start_mock.assert_not_called()

    # -- 10. Magic byte mismatch ---------------------------------------------

    def test_magic_byte_mismatch_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(
            monkeypatch,
            upload_error=UploadHandlerError(
                "Declared MIME type 'application/pdf' does not match detected type"
            ),
        )
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("evil.pdf", b"<html>not a pdf</html>", "application/pdf")},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "Upload failed" in resp.json()["error"]["message"]
        start_mock.assert_not_called()

    # -- 11. Regression: /run JSON endpoint returns same envelope ------------

    def test_regression_run_endpoint_envelope_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(monkeypatch)

        # Call /run (JSON) with a local path (InputFetcher passes it through).
        run_resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"inputs": {"file": "/tmp/fake.pdf"}},
        )
        assert run_resp.status_code == 200
        run_body = run_resp.json()

        # Call /run/upload (multipart).
        upload_resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert upload_resp.status_code == 200
        upload_body = upload_resp.json()

        # Both must share the same top-level success keys.
        expected_keys = {
            "workflow_run_id",
            "status",
            "outputs",
            "elapsed_time_ms",
            "total_steps",
            "created_at",
            "finished_at",
        }
        assert expected_keys <= run_body.keys(), (
            f"missing in /run: {expected_keys - run_body.keys()}"
        )
        assert expected_keys <= upload_body.keys(), (
            f"missing in /run/upload: {expected_keys - upload_body.keys()}"
        )

        assert run_body["status"] == "succeeded"
        assert upload_body["status"] == "succeeded"
        assert "results" in run_body["outputs"]
        assert "results" in upload_body["outputs"]

    # -- 12. DAG-not-started on input failures (cases 6-10) ------------------

    def test_dag_not_started_on_all_input_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One-shot test: verify _start_dag_run is never called for cases 6-10."""
        # We re-test case 6 (oversized) here with explicit tracking.
        # Cases 7-10 already assert_not_called in their own methods; this
        # function provides a single grouped assertion for the task spec.

        # Case 6: oversized
        client_6 = _client(monkeypatch, max_bytes=5)
        start_6 = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_6)
        client_6.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("big.pdf", b"%PDF-1.4", "application/pdf")},
        )
        start_6.assert_not_called()

        # Case 7: missing file
        client_7 = _client(monkeypatch)
        start_7 = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_7)
        client_7.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            data={"something": "else"},
        )
        start_7.assert_not_called()

        # Case 8: two files
        client_8 = _client(monkeypatch)
        start_8 = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_8)
        client_8.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files=[
                ("file", ("a.pdf", b"%PDF-1.4", "application/pdf")),
                ("file", ("b.pdf", b"%PDF-1.4", "application/pdf")),
            ],
        )
        start_8.assert_not_called()

        # Case 9: malformed options
        client_9 = _client(monkeypatch)
        start_9 = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_9)
        client_9.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("ok.pdf", b"%PDF-1.4", "application/pdf")},
            data={"options": "bad json {{{"},
        )
        start_9.assert_not_called()

        # Case 10: magic byte mismatch
        client_10 = _client(monkeypatch, upload_error=UploadHandlerError("bad magic"))
        start_10 = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_10)
        client_10.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("evil.pdf", b"<html>nope</html>", "application/pdf")},
        )
        start_10.assert_not_called()

    # -- 13. Post-parse size check (UploadHandler streaming counter) ----------

    def test_post_parse_size_upload_handler_rejects_oversized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(
            monkeypatch,
            max_bytes=20_000_000,
            upload_error=UploadHandlerError("Upload size exceeds limit (100 bytes)"),
        )
        start_mock = MagicMock()
        monkeypatch.setattr("app.api.public.workflow_runs._start_dag_run", start_mock)
        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={"file": ("big.pdf", b"%PDF-1.4 fake body", "application/pdf")},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_INPUT"
        assert "Upload failed" in resp.json()["error"]["message"]
        start_mock.assert_not_called()

    # -- 14. Rate-limit exceeded → 429 ---------------------------------------

    def test_rate_limit_exceeded_returns_429(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch, mock_rate_limiter=False, rate_limit_per_minute=1)

        headers = {"Authorization": f"Bearer {TEST_KEY}"}
        files = {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}

        r1 = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers=headers,
            files=files,
        )
        assert r1.status_code == 200

        r2 = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers=headers,
            files=files,
        )
        assert r2.status_code == 429
        assert r2.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    # -- 15. Path-traversal filename sanitization -----------------------------

    def test_path_traversal_filename_is_sanitized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch)

        uh = MagicMock()

        async def _receive_verify(file_part, run_id):  # type: ignore[no-untyped-def]
            from app.utils.path_utils import sanitize_filename

            safe = sanitize_filename(file_part.filename or f"{run_id}.bin")
            assert "/" not in safe, f"path separator in sanitized name: {safe}"
            assert "\\" not in safe
            return f"/app/storage/tasks/{run_id}/original/{safe}"

        uh.receive_upload = _receive_verify
        monkeypatch.setattr("app.api.public.workflow_runs.UploadHandler", lambda: uh)

        resp = client.post(
            f"/api/v1/workflows/{TEST_WORKFLOW_ID}/run/upload",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            files={
                "file": (
                    "../../../etc/passwd",
                    b"%PDF-1.4 fake pdf",
                    "application/pdf",
                )
            },
        )
        assert resp.status_code == 200
        saved_path = resp.json()["inputs"]["file"]
        assert saved_path.startswith("/app/storage/tasks/"), f"saved outside storage: {saved_path}"
        assert "/etc/passwd" not in saved_path
