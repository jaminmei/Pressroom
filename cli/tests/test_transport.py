from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pressroom_cli.context import ExecutorContext, FileTokenProvider, StaticTokenProvider
from pressroom_cli.errors import CliError
from pressroom_cli.transport import ApiClient


class FakeResponse:
    def __init__(self, payload: dict[str, object], *, request_id: str = "req-server") -> None:
        self.body = json.dumps(payload).encode()
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["X-Request-Id"] = request_id

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def executor_context(
    tmp_path: Path,
    *,
    token_provider=None,
) -> ExecutorContext:
    return ExecutorContext(
        host="https://platform.example",
        workspace_id="ws-1",
        agent_session_id="ags-1",
        token_provider=token_provider or StaticTokenProvider("pra_session_secret"),
        allowed_file_roots=(tmp_path.resolve(),),
    )


def test_transport_sends_session_context_and_request_id(tmp_path, monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"ok": True})

    monkeypatch.setattr("pressroom_cli.transport.urlopen", fake_urlopen)

    response = ApiClient(executor_context(tmp_path), timeout=4).request("GET", "/api/workflows")

    request = captured["request"]
    assert request.get_header("Authorization") == "Bearer pra_session_secret"
    assert request.get_header("X-workspace-id") == "ws-1"
    assert request.get_header("X-agent-session-id") == "ags-1"
    assert request.get_header("X-request-id")
    assert captured["timeout"] == 4
    assert response.request_id == "req-server"


def test_transport_reads_rotated_token_for_every_request(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "agent-session.token"
    token_file.write_text("pra_first", encoding="utf-8")
    authorizations = []

    def fake_urlopen(request, timeout):
        authorizations.append(request.get_header("Authorization"))
        return FakeResponse({"ok": True})

    monkeypatch.setattr("pressroom_cli.transport.urlopen", fake_urlopen)
    client = ApiClient(
        executor_context(
            tmp_path,
            token_provider=FileTokenProvider(token_file.resolve()),
        )
    )

    client.request("GET", "/api/workflows")
    token_file.write_text("pra_rotated", encoding="utf-8")
    client.request("GET", "/api/workflows")

    assert authorizations == ["Bearer pra_first", "Bearer pra_rotated"]


def test_transport_maps_canonical_http_error(tmp_path, monkeypatch) -> None:
    headers = Message()
    headers["Content-Type"] = "application/json"
    headers["X-Request-Id"] = "req-error"
    error = HTTPError(
        "https://platform.example/api/workflows",
        403,
        "Forbidden",
        headers,
        io.BytesIO(b'{"error":{"code":"WORKSPACE_FORBIDDEN","message":"Denied"}}'),
    )
    monkeypatch.setattr(
        "pressroom_cli.transport.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(CliError) as captured:
        ApiClient(executor_context(tmp_path)).request("GET", "/api/workflows")

    assert captured.value.exit_code == 4
    assert captured.value.code == "WORKSPACE_FORBIDDEN"
    assert captured.value.request_id == "req-error"


def test_transport_refuses_request_when_session_token_is_unavailable(
    tmp_path,
) -> None:
    missing = tmp_path / "missing.token"
    context = executor_context(
        tmp_path,
        token_provider=FileTokenProvider(missing),
    )

    with pytest.raises(CliError) as captured:
        ApiClient(context).request("GET", "/api/workflows")

    assert captured.value.exit_code == 3
    assert captured.value.code == "AGENT_SESSION_TOKEN_UNAVAILABLE"


def test_multipart_request_includes_authorized_files_and_fields(
    tmp_path,
    monkeypatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    captured = {}

    def fake_request(self, method, path, **kwargs):
        captured.update(method=method, path=path, kwargs=kwargs)
        return object()

    monkeypatch.setattr(ApiClient, "request", fake_request)

    ApiClient(executor_context(tmp_path)).multipart_request(
        "POST",
        "/api/uploads",
        files=[("files", str(first)), ("files", str(second))],
        fields={"workflow": "{}"},
    )

    body = captured["kwargs"]["encoded_body"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/uploads"
    assert b'name="workflow"' in body
    assert b'filename="first.txt"' in body
    assert b'filename="second.txt"' in body
    assert b"first" in body
    assert b"second" in body


def test_multipart_request_rejects_file_outside_allowlist(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    context = ExecutorContext(
        host="https://platform.example",
        workspace_id="ws-1",
        agent_session_id="ags-1",
        token_provider=StaticTokenProvider("pra_session_secret"),
        allowed_file_roots=(allowed.resolve(),),
    )

    with pytest.raises(CliError) as captured:
        ApiClient(context).multipart_request(
            "POST", "/api/uploads", files=[("files", str(outside))]
        )

    assert captured.value.code == "FILE_ACCESS_NOT_AUTHORIZED"
