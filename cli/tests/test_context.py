from __future__ import annotations

import os

import pytest
from pressroom_cli.context import ExecutorContext, FileTokenProvider
from pressroom_cli.errors import CliError


def managed_environment(tmp_path) -> dict[str, str]:
    token_file = tmp_path / "agent-session.token"
    token_file.write_text("pra_session_secret", encoding="utf-8")
    return {
        "PRESSROOM_HOST": "https://platform.example/",
        "PRESSROOM_WORKSPACE_ID": "ws-1",
        "PRESSROOM_AGENT_SESSION_ID": "ags-1",
        "PRESSROOM_TOKEN_FILE": str(token_file.resolve()),
        "PRESSROOM_ALLOWED_FILE_ROOTS": os.pathsep.join(
            [str(tmp_path.resolve()), str((tmp_path / "artifacts").resolve())]
        ),
    }


def test_managed_environment_builds_fixed_executor_context(tmp_path) -> None:
    context = ExecutorContext.from_environment(managed_environment(tmp_path))

    assert context.host == "https://platform.example"
    assert context.workspace_id == "ws-1"
    assert context.agent_session_id == "ags-1"
    assert context.token_provider.current_token() == "pra_session_secret"
    assert context.allowed_file_roots[0] == tmp_path.resolve()


def test_managed_environment_reports_all_missing_fields() -> None:
    with pytest.raises(CliError) as captured:
        ExecutorContext.from_environment({})

    assert captured.value.code == "MANAGED_CONTEXT_MISSING"
    assert captured.value.details == {
        "missing": [
            "PRESSROOM_AGENT_SESSION_ID",
            "PRESSROOM_HOST",
            "PRESSROOM_TOKEN_FILE",
            "PRESSROOM_WORKSPACE_ID",
        ]
    }


@pytest.mark.parametrize("token", ["", "   ", "two words", "line\nbreak"])
def test_token_provider_rejects_empty_or_whitespace_tokens(tmp_path, token) -> None:
    token_file = tmp_path / "agent-session.token"
    token_file.write_text(token, encoding="utf-8")

    with pytest.raises(CliError) as captured:
        FileTokenProvider(token_file.resolve()).current_token()

    assert captured.value.code == "AGENT_SESSION_TOKEN_INVALID"


def test_token_provider_requires_an_absolute_existing_file(tmp_path) -> None:
    with pytest.raises(CliError) as captured:
        FileTokenProvider(tmp_path / "missing.token").current_token()

    assert captured.value.code == "AGENT_SESSION_TOKEN_UNAVAILABLE"


def test_file_access_is_limited_to_executor_allowlist(tmp_path) -> None:
    context = ExecutorContext.from_environment(managed_environment(tmp_path))
    inside = tmp_path / "attachment.pdf"
    outside = tmp_path.parent / "outside.pdf"

    assert context.authorize_file_path(inside) == inside.resolve()
    with pytest.raises(CliError) as captured:
        context.authorize_file_path(outside)

    assert captured.value.code == "FILE_ACCESS_NOT_AUTHORIZED"


def test_plain_http_requires_explicit_executor_opt_in(tmp_path) -> None:
    environment = managed_environment(tmp_path)
    environment["PRESSROOM_HOST"] = "http://platform.example"

    with pytest.raises(CliError) as captured:
        ExecutorContext.from_environment(environment)
    assert captured.value.code == "MANAGED_CONTEXT_INVALID"

    environment["PRESSROOM_ALLOW_INSECURE_HTTP"] = "true"
    assert ExecutorContext.from_environment(environment).host == "http://platform.example"
