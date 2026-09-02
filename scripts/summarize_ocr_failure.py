#!/usr/bin/env python3
"""Classify an OCR LLM failure without exposing raw Provider diagnostics.

OCR stderr can contain request URLs, response bodies, prompts, or credentials.
This helper reads that stream locally, emits only allow-listed diagnostic
metadata, and writes a sanitized artifact suitable for a public CI run.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Mapping
from pathlib import Path

REPORT_SCHEMA_VERSION = "pressroom-llm-failure-diagnostic.v1"
MAX_STDERR_BYTES = 2_000_000
HTTP_STATUS_PATTERNS = (
    re.compile(
        r"(?i)\b(?:http(?:/\d(?:\.\d)?)?|status(?:\s+code)?|error(?:\s+code)?)"
        r"\s*[:=]?\s*([45]\d{2})\b"
    ),
    re.compile(
        r"(?i)\b([45]\d{2})\s+(?:bad request|unauthorized|forbidden|not found|"
        r"request timeout|conflict|too many requests|internal server error|bad gateway|"
        r"service unavailable|gateway timeout)\b"
    ),
)

CATEGORY_HINTS = {
    "authentication": "Verify or rotate the CI Provider credential.",
    "rate_limit": "Check Provider quota and rate limits before reducing concurrency.",
    "model": "Verify that the configured model is available on this Provider endpoint.",
    "endpoint_or_protocol": "Verify the base URL, API path, and selected LLM protocol.",
    "provider_error": "Inspect the Provider service for an upstream or availability failure.",
    "timeout": "Inspect Provider latency before changing request or task timeouts.",
    "network": "Check DNS, TLS, and connectivity from the GitHub-hosted runner.",
    "response_format": "Verify that the Provider response matches the selected protocol.",
    "configuration": "Verify the non-secret LLM configuration and required CI secrets.",
    "unknown": "Inspect a restricted Provider-side log or improve the allow-listed classifier.",
}


def _read_source(path: Path, *, tail: bool = False) -> tuple[str, bool, bool]:
    try:
        raw = path.read_bytes()
    except OSError:
        return "", False, False
    truncated = len(raw) > MAX_STDERR_BYTES
    selected = raw[-MAX_STDERR_BYTES:] if tail else raw[:MAX_STDERR_BYTES]
    return selected.decode("utf-8", errors="replace"), True, truncated


def _latest_session(session_root: Path | None) -> Path | None:
    if session_root is None:
        return None
    try:
        candidates = [path for path in session_root.rglob("*.jsonl") if path.is_file()]
        return max(
            candidates,
            key=lambda path: path.stat().st_mtime_ns,
            default=None,
        )
    except OSError:
        return None


def _read_session_errors(path: Path) -> tuple[str, bool, bool]:
    errors: list[str] = []
    retained_bytes = 0
    truncated = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as session:
            for line in session:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping) or record.get("type") not in {
                    "llm_error",
                    "review_item_failed",
                }:
                    continue
                error = record.get("error")
                if not isinstance(error, str) or not error:
                    continue
                encoded = error.encode("utf-8", errors="replace")
                remaining = MAX_STDERR_BYTES - retained_bytes
                if remaining <= 0:
                    truncated = True
                    continue
                selected = encoded[:remaining]
                errors.append(selected.decode("utf-8", errors="replace"))
                retained_bytes += len(selected)
                truncated = truncated or len(encoded) > remaining
    except OSError:
        return "", False, False
    return "\n".join(errors), bool(errors), truncated


def _http_statuses(stderr: str) -> list[int]:
    statuses: set[int] = set()
    for pattern in HTTP_STATUS_PATTERNS:
        statuses.update(int(match) for match in pattern.findall(stderr))
    return sorted(statuses)


def _matches(stderr: str, *patterns: str) -> bool:
    return any(re.search(pattern, stderr, flags=re.IGNORECASE) for pattern in patterns)


def _select_status(statuses: list[int]) -> int | None:
    for preferred in (401, 403, 429, 404, 405, 400, 415, 422, 408, 409):
        if preferred in statuses:
            return preferred
    provider_statuses = [status for status in statuses if 500 <= status <= 599]
    return provider_statuses[0] if provider_statuses else (statuses[0] if statuses else None)


def classify_failure(stderr: str) -> tuple[str, int | None]:
    statuses = _http_statuses(stderr)
    status = _select_status(statuses)
    authentication_signal = _matches(
        stderr,
        r"\bunauthori[sz]ed\b",
        r"\bforbidden\b",
        r"invalid (?:api[- ]?)?key",
        r"authentication failed",
        r"credential.*(?:invalid|expired)",
    )
    rate_limit_signal = _matches(
        stderr,
        r"rate[- ]?limit",
        r"too many requests",
        r"insufficient quota",
        r"quota (?:exceeded|exhausted)",
        r"resource exhausted",
    )
    model_signal = _matches(
        stderr,
        r"model.*(?:not found|not available|unsupported|invalid|does not exist)",
        r"unknown model",
        r"no (?:available|healthy) model",
    )

    if status in {401, 403}:
        return "authentication", status
    if status == 429:
        return "rate_limit", status
    if model_signal:
        return "model", status
    if status in {400, 404, 405, 415, 422} or _matches(
        stderr,
        r"invalid (?:base )?url",
        r"unsupported (?:api|protocol|media type)",
        r"endpoint.*not found",
        r"method not allowed",
    ):
        return "endpoint_or_protocol", status
    if (
        status in {408, 409}
        or (status is not None and 500 <= status <= 599)
        or _matches(
            stderr,
            r"internal server error",
            r"bad gateway",
            r"service unavailable",
            r"gateway timeout",
            r"upstream.*(?:error|unavailable|failed)",
        )
    ):
        return "provider_error", status
    if _matches(stderr, r"deadline exceeded", r"timed out", r"\btimeout\b"):
        return "timeout", status
    if _matches(
        stderr,
        r"connection (?:refused|reset|closed|error)",
        r"no such host",
        r"network is unreachable",
        r"temporary failure in name resolution",
        r"\bdns\b",
        r"\btls\b",
        r"\bx509\b",
        r"certificate (?:error|verify|verification|signed)",
        r"dial tcp",
    ):
        return "network", status
    if _matches(
        stderr,
        r"failed to (?:decode|parse|unmarshal)",
        r"invalid character.*json",
        r"unexpected end of json",
        r"empty (?:assistant )?response",
        r"response.*(?:malformed|invalid format)",
    ):
        return "response_format", status
    if _matches(
        stderr,
        r"no valid llm endpoint configured",
        r"required.*configuration.*missing",
        r"invalid configuration",
    ):
        return "configuration", status
    if authentication_signal:
        return "authentication", status
    if rate_limit_signal:
        return "rate_limit", status
    return "unknown", status


def _workflow_escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def _diagnostic_message(*, category: str, http_status: int | None, retry_observed: bool) -> str:
    parts = [f"category={category}"]
    if http_status is not None:
        parts.append(f"http_status={http_status}")
    parts.append(f"retry_observed={'true' if retry_observed else 'false'}")
    return "; ".join(parts) + ". Raw Provider diagnostics are withheld."


def _write_summary(
    path: Path,
    *,
    category: str,
    http_status: int | None,
    retry_observed: bool,
    hint: str,
) -> None:
    safe_category = html.escape(category, quote=True)
    safe_status = str(http_status) if http_status is not None else "Not detected"
    safe_hint = html.escape(hint, quote=True)
    with path.open("a", encoding="utf-8") as summary:
        summary.writelines(
            (
                "## LLM public-release review infrastructure failure\n\n",
                f"- Category: `{safe_category}`\n",
                f"- HTTP status: `{safe_status}`\n",
                f"- Retry signal observed: `{'yes' if retry_observed else 'no'}`\n",
                f"- Suggested check: {safe_hint}\n\n",
                "Raw Provider diagnostics, response bodies, endpoints, and credentials "
                "are intentionally withheld. The release remains blocked.\n",
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--session-root", type=Path)
    parser.add_argument("--sanitized-diagnostic", required=True, type=Path)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument("--github-step-summary", type=Path)
    args = parser.parse_args()

    stderr, stderr_present, stderr_truncated = _read_source(args.stderr)
    session_path = _latest_session(args.session_root)
    session_text, session_present, session_truncated = (
        _read_session_errors(session_path) if session_path is not None else ("", False, False)
    )
    diagnostic_input = f"{stderr}\n{session_text}"
    category, http_status = classify_failure(diagnostic_input)
    retry_observed = _matches(
        diagnostic_input,
        r"\bretrying (?:the )?(?:llm |http |api )?request\b",
        r"\brequest retr(?:y|ied|ies)\b",
        r"max(?:imum)? retries",
        r"retry attempts?",
        r"after \d+ retries",
    )
    all_tasks_failed = bool(
        re.search(r"all \d+ file review\(s\) failed", diagnostic_input, flags=re.IGNORECASE)
    )
    hint = CATEGORY_HINTS[category]
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "infrastructure_failure",
        "category": category,
        "http_status": http_status,
        "retry_observed": retry_observed,
        "all_tasks_failed": all_tasks_failed,
        "stderr_present": stderr_present,
        "stderr_truncated": stderr_truncated,
        "session_diagnostic_present": session_present,
        "session_diagnostic_truncated": session_truncated,
        "review_exit_code": args.exit_code,
        "suggested_check": hint,
    }
    args.sanitized_diagnostic.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    message = _diagnostic_message(
        category=category,
        http_status=http_status,
        retry_observed=retry_observed,
    )
    print(f"LLM public-release sensitivity review did not complete: {message}")
    if args.github_annotations:
        title = _workflow_escape("LLM release review failed", property_value=True)
        print(f"::error title={title}::{_workflow_escape(message)}")
    if args.github_step_summary is not None:
        _write_summary(
            args.github_step_summary,
            category=category,
            http_status=http_status,
            retry_observed=retry_observed,
            hint=hint,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
