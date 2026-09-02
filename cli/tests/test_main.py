from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pressroom_cli.context import ExecutorContext, StaticTokenProvider
from pressroom_cli.main import build_parser, run
from pressroom_cli.runtime import Runtime
from pressroom_cli.transport import ApiResponse


def runtime(tmp_path: Path) -> tuple[Runtime, io.StringIO, io.StringIO]:
    stdout = io.StringIO()
    stderr = io.StringIO()
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
            stderr=stderr,
        ),
        stdout,
        stderr,
    )


@pytest.mark.parametrize(
    "root",
    ["auth", "config", "workspace", "doctor", "commands"],
)
def test_non_business_command_roots_are_not_installed(root) -> None:
    parser = build_parser()
    root_action = next(
        action for action in parser._actions if getattr(action, "dest", None) == "root_command"
    )

    assert root not in root_action.choices


@pytest.mark.parametrize(
    "argument",
    [
        "--profile",
        "--host",
        "--base-url",
        "--workspace",
        "--host=https://evil.example",
    ],
)
def test_managed_context_overrides_are_rejected(tmp_path, argument) -> None:
    active, stdout, _ = runtime(tmp_path)
    argv = ["workflow", "list", argument]
    if "=" not in argument:
        argv.append("override")
    argv.append("--json")

    exit_code = run(argv, runtime=active)

    payload = json.loads(stdout.getvalue())
    assert exit_code == 2
    assert payload["error"]["code"] == "MANAGED_CONTEXT_OVERRIDE_FORBIDDEN"


def test_missing_managed_context_has_stable_error_envelope() -> None:
    stdout = io.StringIO()
    active = Runtime(
        environment={},
        stdin=io.StringIO(),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    exit_code = run(["workflow", "list", "--json"], runtime=active)

    payload = json.loads(stdout.getvalue())
    assert exit_code == 8
    assert payload["error"]["code"] == "MANAGED_CONTEXT_MISSING"


def test_file_upload_uses_executor_context_and_returns_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    active, stdout, _ = runtime(tmp_path)
    source = tmp_path / "sample.txt"
    source.write_text("sample", encoding="utf-8")

    def fake_upload(self, path):
        assert self.context.workspace_id == "ws-1"
        assert self.context.agent_session_id == "ags-1"
        assert path == str(source)
        return ApiResponse(
            data={"file_id": "file-1", "filename": "sample.txt"},
            status=201,
            request_id="req-upload",
            content_type="application/json",
        )

    monkeypatch.setattr("pressroom_cli.main.ApiClient.upload_file", fake_upload)

    exit_code = run(["file", "upload", "--file", str(source), "--json"], runtime=active)

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["data"]["file_id"] == "file-1"
    assert payload["request_id"] == "req-upload"


def test_file_download_writes_only_to_allowed_root(tmp_path, monkeypatch) -> None:
    active, stdout, _ = runtime(tmp_path)
    output = tmp_path / "result.txt"
    monkeypatch.setattr(
        "pressroom_cli.main.ApiClient.request",
        lambda self, method, path, **kwargs: ApiResponse(
            data={"content_type": "text/plain", "size": 6},
            status=200,
            request_id="req-download",
            content_type="text/plain",
            raw=b"result",
        ),
    )

    assert (
        run(
            ["file", "download", "file-1", "--output", str(output), "--json"],
            runtime=active,
        )
        == 0
    )
    assert output.read_bytes() == b"result"

    stdout.seek(0)
    stdout.truncate()
    outside = tmp_path.parent / "outside.txt"
    assert (
        run(
            ["file", "download", "file-1", "--output", str(outside), "--json"],
            runtime=active,
        )
        == 8
    )
    assert json.loads(stdout.getvalue())["error"]["code"] == "FILE_ACCESS_NOT_AUTHORIZED"


def test_file_delete_checks_impact_before_confirmed_delete(tmp_path, monkeypatch) -> None:
    active, stdout, _ = runtime(tmp_path)
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path))
        data = {"can_delete": True, "run_references": 0} if method == "GET" else None
        return ApiResponse(
            data=data,
            status=200 if method == "GET" else 204,
            request_id="req-delete",
            content_type="application/json",
        )

    monkeypatch.setattr("pressroom_cli.main.ApiClient.request", fake_request)

    exit_code = run(["file", "delete", "file-1", "--yes", "--json"], runtime=active)

    assert exit_code == 0
    assert calls == [
        ("GET", "/api/files/file-1/deletion-impact"),
        ("DELETE", "/api/files/file-1"),
    ]
    assert json.loads(stdout.getvalue())["data"]["deleted"] is True
