from __future__ import annotations

import io
import json
from pathlib import Path

from pressroom_cli.context import ExecutorContext, StaticTokenProvider
from pressroom_cli.main import Runtime, run
from pressroom_cli.transport import ApiResponse


def _runtime(tmp_path: Path) -> tuple[Runtime, io.StringIO]:
    stdout = io.StringIO()
    context = ExecutorContext(
        host="https://platform.example",
        workspace_id="ws-1",
        agent_session_id="ags-1",
        token_provider=StaticTokenProvider("pra_session_secret"),
        allowed_file_roots=(tmp_path.resolve(),),
    )
    return (
        Runtime(
            context=context,
            stdin=io.StringIO(),
            stdout=stdout,
            stderr=io.StringIO(),
        ),
        stdout,
    )


def test_workflow_create_loads_definition_and_uses_canonical_route(tmp_path, monkeypatch) -> None:
    active, stdout = _runtime(tmp_path)
    definition = tmp_path / "workflow.json"
    definition.write_text('{"nodes": [], "connections": []}', encoding="utf-8")
    captured = {}

    def fake_request(self, method, path, **kwargs):
        captured.update(method=method, path=path, kwargs=kwargs)
        return ApiResponse(
            data={"workflow_id": "wf-1", "version": 1},
            status=201,
            request_id="req-workflow-create",
            content_type="application/json",
        )

    monkeypatch.setattr("pressroom_cli.domain_commands.ApiClient.request", fake_request)

    exit_code = run(
        [
            "workflow",
            "create",
            "--name",
            "Example",
            "--definition",
            str(definition),
            "--json",
        ],
        runtime=active,
    )

    assert exit_code == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/workflows"
    assert captured["kwargs"]["body"]["definition"] == {
        "nodes": [],
        "connections": [],
    }
    assert json.loads(stdout.getvalue())["request_id"] == "req-workflow-create"


def test_workflow_definition_update_requires_base_version(tmp_path) -> None:
    active, stdout = _runtime(tmp_path)
    definition = tmp_path / "workflow.json"
    definition.write_text('{"nodes": [], "connections": []}', encoding="utf-8")

    exit_code = run(
        [
            "workflow",
            "update",
            "wf-1",
            "--definition",
            str(definition),
            "--json",
        ],
        runtime=active,
    )

    assert exit_code == 2
    assert json.loads(stdout.getvalue())["error"]["code"] == "CLI_USAGE"


def test_workflow_execute_requires_confirmation(tmp_path, monkeypatch) -> None:
    active, stdout = _runtime(tmp_path)
    monkeypatch.setattr(
        "pressroom_cli.domain_commands.ApiClient.request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("request must not be sent without confirmation")
        ),
    )

    exit_code = run(
        ["workflow", "execute", "wf-1", "--file-id", "file-1", "--json"],
        runtime=active,
    )

    assert exit_code == 2
    assert json.loads(stdout.getvalue())["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_run_wait_polls_until_terminal_without_remote_cancel(tmp_path, monkeypatch) -> None:
    active, stdout = _runtime(tmp_path)
    responses = iter(["running", "completed"])
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path))
        return ApiResponse(
            data={"task_id": "run-1", "status": next(responses)},
            status=200,
            request_id="req-wait",
            content_type="application/json",
        )

    monkeypatch.setattr("pressroom_cli.domain_commands.ApiClient.request", fake_request)
    monkeypatch.setattr("pressroom_cli.domain_commands.time.sleep", lambda _seconds: None)

    exit_code = run(
        ["run", "wait", "run-1", "--interval", "0.01", "--json"],
        runtime=active,
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "/api/tasks/run-1"),
        ("GET", "/api/tasks/run-1"),
    ]
    assert json.loads(stdout.getvalue())["data"]["status"] == "completed"


def test_document_batch_upload_preserves_partial_exit_code(tmp_path, monkeypatch) -> None:
    active, stdout = _runtime(tmp_path)
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    captured = {}

    def fake_multipart(self, method, path, **kwargs):
        captured.update(method=method, path=path, kwargs=kwargs)
        return ApiResponse(
            data={"status": "partial", "uploaded_count": 1, "failed_count": 1},
            status=207,
            request_id="req-upload",
            content_type="application/json",
        )

    monkeypatch.setattr(
        "pressroom_cli.domain_commands.ApiClient.multipart_request",
        fake_multipart,
    )

    exit_code = run(
        [
            "test-set",
            "document",
            "upload",
            "ts-1",
            "--file",
            str(first),
            "--file",
            str(second),
            "--yes",
            "--json",
        ],
        runtime=active,
    )

    assert exit_code == 12
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/test-sets/ts-1/documents/upload"
    assert captured["kwargs"]["files"] == [
        ("files", str(first)),
        ("files", str(second)),
    ]
    assert json.loads(stdout.getvalue())["ok"] is True


def test_comparison_refresh_uses_canonical_write_route(tmp_path, monkeypatch) -> None:
    active, _ = _runtime(tmp_path)
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path))
        return ApiResponse(
            data={"status": "completed"},
            status=200,
            request_id="req-comparison",
            content_type="application/json",
        )

    monkeypatch.setattr("pressroom_cli.domain_commands.ApiClient.request", fake_request)

    assert (
        run(
            [
                "evaluation",
                "comparison",
                "refresh",
                "eval-1",
                "result-1",
                "--yes",
                "--json",
            ],
            runtime=active,
        )
        == 0
    )
    assert calls == [
        (
            "POST",
            "/api/evaluation-runs/eval-1/results/result-1/comparison",
        )
    ]


def test_all_failed_document_batch_uses_validation_exit(tmp_path, monkeypatch) -> None:
    active, stdout = _runtime(tmp_path)
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken")
    monkeypatch.setattr(
        "pressroom_cli.domain_commands.ApiClient.multipart_request",
        lambda self, method, path, **kwargs: ApiResponse(
            data={"status": "failure", "uploaded_count": 0, "failed_count": 1},
            status=201,
            request_id="req-failed-batch",
            content_type="application/json",
        ),
    )

    exit_code = run(
        [
            "test-set",
            "document",
            "upload",
            "ts-1",
            "--file",
            str(source),
            "--yes",
            "--json",
        ],
        runtime=active,
    )

    assert exit_code == 7
    assert json.loads(stdout.getvalue())["error"]["code"] == "BATCH_UPLOAD_FAILED"


def test_unhealthy_diagnostic_preserves_payload_and_uses_remote_exit(
    tmp_path,
    monkeypatch,
) -> None:
    active, stdout = _runtime(tmp_path)
    monkeypatch.setattr(
        "pressroom_cli.domain_commands.ApiClient.request",
        lambda self, method, path, **kwargs: ApiResponse(
            data={
                "operation": "provider.health",
                "status": "unhealthy",
                "error_code": "PROVIDER_DIAGNOSTIC_FAILED",
            },
            status=200,
            request_id="req-unhealthy",
            content_type="application/json",
        ),
    )

    exit_code = run(
        ["provider", "health", "provider-1", "--yes", "--json"],
        runtime=active,
    )

    assert exit_code == 11
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True
    assert payload["data"]["status"] == "unhealthy"


def test_deferred_run_mutations_are_not_installed(tmp_path) -> None:
    active, _ = _runtime(tmp_path)

    assert run(["run", "reset", "run-1", "--json"], runtime=active) == 2
    assert run(["run", "node", "retry", "run-1", "node-1", "--json"], runtime=active) == 2
