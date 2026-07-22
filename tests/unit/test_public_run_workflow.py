"""API-level tests for the public /run endpoint with InputFetcher wired in.

Covers public run response behavior:
  - POST /run with URL inputs.file (fetcher mocked) → 200 succeeded with outputs
  - Failed fetch → 400 INVALID_INPUT and no task_runs row persisted

The FastAPI handler is invoked directly (no ASGI test client) so we can mock
the dependencies (workflow store, task repo, InputFetcher) without spinning
up the app.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.public.auth import ApiKeyIdentity
from app.api.public.error_response import PublicApiError
from app.api.public.workflow_runs import RunWorkflowRequest, run_workflow
from app.services.input_fetcher import InputFetchError

TEST_WORKSPACE_ID = "ws_public_run"


def _api_key_identity(workflow_id: str = "wf_demo") -> ApiKeyIdentity:
    return ApiKeyIdentity(
        api_key_id="key_public_run",
        key_prefix="dca_public",
        workflow_id=workflow_id,
        workspace_id=TEST_WORKSPACE_ID,
    )


class _FakeRequest:
    """Minimal FastAPI Request stand-in carrying app.state."""

    def __init__(self) -> None:
        self.app = MagicMock()


def _setup_handler_mocks(
    *,
    input_nodes_present: bool = True,
    fetcher_side_effect: BaseException | None = None,
    fetcher_return: str | None = None,
) -> tuple[dict[str, Any], MagicMock, MagicMock, MagicMock]:
    """Patch all handler deps; return (patchers, fake_start, fake_repo, fetcher_inst)."""
    patchers: dict[str, Any] = {
        "start": patch("app.api.public.workflow_runs._start_dag_run"),
        "repo": patch("app.api.public.workflow_runs.TaskRunRepository"),
        "wfs": patch("app.api.public.workflow_runs.get_workflow_store"),
        "settings": patch("app.api.public.workflow_runs.get_settings"),
        "wait": patch("app.api.public.workflow_runs.await_run_terminal", new_callable=AsyncMock),
        "fetcher": patch("app.api.public.workflow_runs.InputFetcher"),
    }
    started = {k: p.start() for k, p in patchers.items()}

    fake_start = started["start"]
    fake_start.return_value = None

    fake_repo_inst = MagicMock()
    fake_repo_inst.upsert_snapshot = AsyncMock(return_value=None)
    started["repo"].return_value = fake_repo_inst

    nodes = []
    if input_nodes_present:
        nodes = [MagicMock(id="input_1", type="input/file", config={"file": "$file_0"})]
    started["wfs"].return_value.get.return_value = MagicMock(
        definition=MagicMock(nodes=nodes), published_version=1
    )

    started["settings"].return_value.workflow_api_timeout_seconds = 300

    fake_snap = MagicMock(
        status="completed",
        workspace_id=TEST_WORKSPACE_ID,
        results=[{"content": "extracted text"}],
        duration_ms=1234,
        node_summary={"n1": 1},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        error=None,
    )
    started["wait"].return_value = fake_snap

    fetcher_inst = MagicMock()
    if fetcher_side_effect is not None:
        fetcher_inst.resolve_input_file = AsyncMock(side_effect=fetcher_side_effect)
    else:
        fetcher_inst.resolve_input_file = AsyncMock(return_value=fetcher_return)
    started["fetcher"].return_value = fetcher_inst

    return patchers, fake_start, fake_repo_inst, fetcher_inst


def _teardown(patchers: dict[str, Any]) -> None:
    for p in patchers.values():
        p.stop()


# ---------- 4.5a: URL input → 200 succeeded ----------


@pytest.mark.asyncio()
async def test_run_with_url_input_returns_200() -> None:
    patchers, fake_start, _, fetcher_inst = _setup_handler_mocks(
        fetcher_return="/tmp/tasks/r1/original/invoice.pdf"
    )
    try:
        resp = await run_workflow(
            workflow_id="wf_demo",
            request=_FakeRequest(),
            api_key_identity=_api_key_identity(),
            payload=RunWorkflowRequest(inputs={"file": "https://example.com/invoice.pdf"}),
        )

        # Status 200 with the documented public response shape
        assert resp.status_code == 200, resp.status_code
        body = resp.body.decode() if hasattr(resp, "body") else ""
        assert '"status":"succeeded"' in body.replace(" ", ""), body

        # InputFetcher was called with the URL and a task_-prefixed run_id
        fetcher_inst.resolve_input_file.assert_awaited_once()
        args = fetcher_inst.resolve_input_file.call_args.args
        assert args[0] == "https://example.com/invoice.pdf"
        assert args[1].startswith("task_"), args[1]

        # _start_dag_run got the resolved local path in input_bindings
        start_kwargs = fake_start.call_args.kwargs
        assert start_kwargs["workspace_id"] == TEST_WORKSPACE_ID
        bound = start_kwargs["input_bindings"]["input_1"]
        assert bound.file_path == "/tmp/tasks/r1/original/invoice.pdf"
    finally:
        _teardown(patchers)


# ---------- 4.5b: failed fetch → 400 INVALID_INPUT, no task_runs row ----------


@pytest.mark.asyncio()
async def test_run_with_failed_fetch_returns_400_and_no_run_started() -> None:
    patchers, fake_start, fake_repo, _ = _setup_handler_mocks(
        fetcher_side_effect=InputFetchError("SSRF guard rejected host: 127.0.0.1"),
    )
    try:
        with pytest.raises(PublicApiError) as exc_info:
            await run_workflow(
                workflow_id="wf_demo",
                request=_FakeRequest(),
                api_key_identity=_api_key_identity(),
                payload=RunWorkflowRequest(inputs={"file": "http://127.0.0.1/x"}),
            )

        assert exc_info.value.status_code == 400, exc_info.value.status_code
        assert exc_info.value.code == "INVALID_INPUT", exc_info.value.code
        assert "SSRF" in exc_info.value.message, exc_info.value.message

        # CRITICAL: no half-started run, no task_runs row
        assert not fake_start.called, "_start_dag_run was called on fetch failure"
        assert not fake_repo.upsert_snapshot.called, "upsert_snapshot was called on fetch failure"

    finally:
        _teardown(patchers)


# ---------- 4.5c: local path bypasses fetcher fully (uses real InputFetcher) ----------


@pytest.mark.asyncio()
async def test_run_with_local_path_uses_verbatim_path() -> None:
    # Patch everything EXCEPT InputFetcher — exercise the real bypass.
    patchers: dict[str, Any] = {
        "start": patch("app.api.public.workflow_runs._start_dag_run"),
        "repo": patch("app.api.public.workflow_runs.TaskRunRepository"),
        "wfs": patch("app.api.public.workflow_runs.get_workflow_store"),
        "settings": patch("app.api.public.workflow_runs.get_settings"),
        "wait": patch("app.api.public.workflow_runs.await_run_terminal", new_callable=AsyncMock),
    }
    started = {k: p.start() for k, p in patchers.items()}

    fake_start = started["start"]
    fake_start.return_value = None
    fake_repo_inst = MagicMock()
    fake_repo_inst.upsert_snapshot = AsyncMock(return_value=None)
    started["repo"].return_value = fake_repo_inst
    started["wfs"].return_value.get.return_value = MagicMock(
        definition=MagicMock(
            nodes=[MagicMock(id="input_1", type="input/file", config={"file": "$file_0"})]
        ),
        published_version=1,
    )
    started["settings"].return_value.workflow_api_timeout_seconds = 300
    started["wait"].return_value = MagicMock(
        status="completed",
        results=[{"content": "ok"}],
        duration_ms=1,
        node_summary={"n": 1},
        created_at=None,
        completed_at=None,
        error=None,
    )
    try:
        local = "/app/storage/tasks/r1/original/y.pdf"
        resp = await run_workflow(
            workflow_id="wf_demo",
            request=_FakeRequest(),
            api_key_identity=_api_key_identity(),
            payload=RunWorkflowRequest(inputs={"file": local}),
        )
        assert resp.status_code == 200, resp.status_code
        bound = fake_start.call_args.kwargs["input_bindings"]["input_1"]
        assert bound.file_path == local, bound.file_path
    finally:
        _teardown(patchers)


# ---------- 4.5d: missing inputs.file on a workflow that needs it ----------


@pytest.mark.asyncio()
async def test_run_with_missing_file_input_returns_400() -> None:
    patchers, fake_start, fake_repo, _ = _setup_handler_mocks(fetcher_return="unused")
    try:
        with pytest.raises(PublicApiError) as exc_info:
            await run_workflow(
                workflow_id="wf_demo",
                request=_FakeRequest(),
                api_key_identity=_api_key_identity(),
                payload=RunWorkflowRequest(inputs={}),
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "INVALID_INPUT"
        assert "inputs.file is required" in exc_info.value.message
        # No fetcher call, no run started.
        assert not fake_start.called
        assert not fake_repo.upsert_snapshot.called
    finally:
        _teardown(patchers)
