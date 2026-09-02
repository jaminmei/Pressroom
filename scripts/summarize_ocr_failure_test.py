from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("summarize_ocr_failure.py")


def _run(
    tmp_path: Path,
    stderr_text: str,
    *,
    session_text: str | None = None,
    github_annotations: bool = True,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object], str]:
    stderr_path = tmp_path / "ocr-stderr.log"
    diagnostic_path = tmp_path / "diagnostic.json"
    summary_path = tmp_path / "summary.md"
    stderr_path.write_text(stderr_text, encoding="utf-8")
    command = [
        sys.executable,
        str(SCRIPT),
        "--stderr",
        str(stderr_path),
        "--sanitized-diagnostic",
        str(diagnostic_path),
        "--exit-code",
        "1",
        "--github-step-summary",
        str(summary_path),
    ]
    if session_text is not None:
        session_root = tmp_path / "sessions" / "repository"
        session_root.mkdir(parents=True)
        (session_root / "session.jsonl").write_text(session_text, encoding="utf-8")
        command.extend(("--session-root", str(tmp_path / "sessions")))
    if github_annotations:
        command.append("--github-annotations")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    summary = summary_path.read_text(encoding="utf-8")
    return result, diagnostic, summary


@pytest.mark.parametrize(
    ("stderr_text", "category", "status"),
    [
        ("API error status code: 401 unauthorized", "authentication", 401),
        ("HTTP/1.1 429 Too Many Requests; retrying", "rate_limit", 429),
        ("request failed: status=503 Service Unavailable", "provider_error", 503),
        ("POST returned 404 Not Found", "endpoint_or_protocol", 404),
        ("status code: 404 authentication failed", "endpoint_or_protocol", 404),
        ("model GLM-test is not available", "model", None),
        ("dial tcp: connection refused", "network", None),
        ("context deadline exceeded", "timeout", None),
        ("failed to decode response JSON", "response_format", None),
        ("no valid LLM endpoint configured", "configuration", None),
        ("review failed for an unspecified reason", "unknown", None),
    ],
)
def test_classifies_allow_listed_failure_metadata(
    tmp_path: Path,
    stderr_text: str,
    category: str,
    status: int | None,
) -> None:
    result, diagnostic, summary = _run(tmp_path, stderr_text)

    assert result.returncode == 0
    assert diagnostic["schema_version"] == "pressroom-llm-failure-diagnostic.v1"
    assert diagnostic["category"] == category
    assert diagnostic["http_status"] == status
    assert diagnostic["review_exit_code"] == 1
    assert category in result.stdout
    assert category in summary
    assert result.stderr == ""


def test_raw_provider_data_never_leaves_the_classifier(tmp_path: Path) -> None:
    secret = "super-secret-provider-token"
    private_url = "https://private-provider.example.invalid/v1/messages"
    upstream_body = "confidential upstream response body"
    stderr_text = (
        f"POST {private_url} Authorization: Bearer {secret}\n"
        f"HTTP/1.1 429 Too Many Requests: {upstream_body}\n"
        "retrying request\n"
    )

    result, diagnostic, summary = _run(tmp_path, stderr_text)
    emitted = result.stdout + result.stderr + summary + json.dumps(diagnostic)

    assert diagnostic["category"] == "rate_limit"
    assert diagnostic["http_status"] == 429
    assert diagnostic["retry_observed"] is True
    assert secret not in emitted
    assert private_url not in emitted
    assert upstream_body not in emitted
    assert "Raw Provider diagnostics are withheld" in result.stdout


def test_classifies_persisted_session_error_without_exposing_session_data(
    tmp_path: Path,
) -> None:
    secret = "session-only-secret"
    session_text = (
        '{"type":"review_item_failed","error":"LLM completion error: '
        f'status code: 503 upstream unavailable {secret}"}}\n'
    )

    result, diagnostic, summary = _run(
        tmp_path,
        "Error: all 5 file review(s) failed",
        session_text=session_text,
    )
    emitted = result.stdout + result.stderr + summary + json.dumps(diagnostic)

    assert diagnostic["category"] == "provider_error"
    assert diagnostic["http_status"] == 503
    assert diagnostic["session_diagnostic_present"] is True
    assert diagnostic["all_tasks_failed"] is True
    assert secret not in emitted


def test_ignores_model_phrases_outside_session_error_records(tmp_path: Path) -> None:
    secret = "ignored-session-secret"
    private_url = "https://ignored-provider.example.invalid/v1/messages"
    session_text = (
        '{"type":"llm_request","messages":[{"content":"model is not available; '
        f"Authorization: Bearer {secret}; endpoint {private_url}"
        '"}]}\n'
        '{"type":"review_item_failed","error":"status code: 404 Not Found"}\n'
    )

    result, diagnostic, summary = _run(
        tmp_path,
        "Error: all 2 file review(s) failed",
        session_text=session_text,
    )
    emitted = result.stdout + result.stderr + summary + json.dumps(diagnostic)

    assert diagnostic["category"] == "endpoint_or_protocol"
    assert diagnostic["http_status"] == 404
    assert secret not in emitted
    assert private_url not in emitted


def test_missing_stderr_produces_an_unknown_sanitized_diagnostic(tmp_path: Path) -> None:
    stderr_path = tmp_path / "missing.log"
    diagnostic_path = tmp_path / "diagnostic.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--stderr",
            str(stderr_path),
            "--sanitized-diagnostic",
            str(diagnostic_path),
            "--exit-code",
            "7",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert diagnostic["category"] == "unknown"
    assert diagnostic["stderr_present"] is False
    assert diagnostic["review_exit_code"] == 7


def test_resume_hint_is_not_misreported_as_an_http_retry(tmp_path: Path) -> None:
    result, diagnostic, _ = _run(
        tmp_path,
        "[ocr] Session: abc (retry with: --resume abc)\nError: review failed",
    )

    assert result.returncode == 0
    assert diagnostic["retry_observed"] is False
