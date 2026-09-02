#!/usr/bin/env python3
"""Prepare a sanitized, human-reviewable LLM release-sensitivity report.

The OCR JSON result can contain source snippets and model reasoning. This helper
never emits or persists those fields. A valid model result is advisory: findings
request human review but do not fail the job. Missing or malformed review output
remains a hard infrastructure failure so a release cannot silently bypass the
review stage.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "pressroom-release-sensitivity.v1"
ANNOTATION_TITLE = "Public release sensitivity finding"
ANNOTATION_MESSAGE = (
    "Human review required: inspect the referenced source location for release-sensitive "
    "information. Raw model text is withheld."
)
KNOWN_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})


def _display_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "<unknown path>"
    return "".join(character if character.isprintable() else " " for character in value)[:240]


def _display_line(value: object) -> str:
    return (
        str(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else "?"
    )


def _normalize_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _safe_category(value: object) -> str:
    return "security" if _normalize_label(value) == "security" else "other"


def _safe_severity(value: object) -> str:
    normalized = _normalize_label(value)
    return normalized if normalized in KNOWN_SEVERITIES else "unknown"


def _annotation_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > 240
        or "\x00" in candidate
        or "\r" in candidate
        or "\n" in candidate
        or candidate.startswith(("/", "\\"))
    ):
        return None
    normalized = candidate.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        return None
    return normalized


def _line_number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _sanitize_finding(comment: Mapping[str, Any]) -> dict[str, object]:
    path = _annotation_path(comment.get("path"))
    line = _line_number(comment.get("start_line"))
    return {
        "path": path,
        "start_line": line,
        "category": _safe_category(comment.get("category")),
        "severity": _safe_severity(comment.get("severity")),
        "actionable": path is not None and line is not None,
    }


def _escape_workflow_command(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def _summary_path(value: object) -> str:
    return html.escape(_display_path(value), quote=True).replace("|", "&#124;")


def _emit_advisory_annotation(finding: Mapping[str, object]) -> None:
    path = finding.get("path")
    line = finding.get("start_line")
    title = _escape_workflow_command(ANNOTATION_TITLE, property_value=True)
    message = _escape_workflow_command(ANNOTATION_MESSAGE)
    if not isinstance(path, str) or not isinstance(line, int):
        print(
            f"::warning title={title}::A sensitivity finding lacks an actionable "
            "repository path and line; inspect the sanitized report. Raw model text is withheld."
        )
        return
    annotation_path = _escape_workflow_command(path, property_value=True)
    print(f"::warning file={annotation_path},line={line},title={title}::{message}")


def _write_summary(
    summary_path: Path,
    *,
    findings: Sequence[Mapping[str, object]],
    report_digest: str | None = None,
    result_error: str | None = None,
) -> None:
    lines: Sequence[str]
    if result_error is not None:
        lines = (
            "## LLM public-release sensitivity review\n\n",
            "**Status:** Review infrastructure failed.\n\n",
            f"{result_error}\n\n",
            "No model response content was retained or displayed.\n",
        )
    else:
        status = "Human review required" if findings else "No findings"
        actionable_count = sum(bool(finding.get("actionable")) for finding in findings)
        lines_list = [
            "## LLM public-release sensitivity review\n\n",
            f"**Status:** {status}\n\n",
            f"Findings requiring review: **{len(findings)}**  \n",
            f"Actionable source locations: **{actionable_count}**  \n",
            f"Unactionable locations: **{len(findings) - actionable_count}**\n\n",
        ]
        if report_digest is not None:
            lines_list.append(f"Report digest: `{report_digest}`\n\n")
        if findings:
            lines_list.extend(
                (
                    "| File | Line | Category | Severity | Review |\n",
                    "| --- | ---: | --- | --- | --- |\n",
                )
            )
            for finding in findings:
                location_status = (
                    "Inspect source" if finding.get("actionable") else "Inspect report"
                )
                lines_list.append(
                    "| "
                    f"{_summary_path(finding.get('path'))} | "
                    f"{_display_line(finding.get('start_line'))} | "
                    f"{finding.get('category', 'other')} | "
                    f"{finding.get('severity', 'unknown')} | "
                    f"{location_status} |\n"
                )
            lines_list.append(
                "\nApproval attests that every finding in this report was reviewed. "
                "Raw model text and source snippets are intentionally withheld.\n"
            )
        lines = tuple(lines_list)
    with summary_path.open("a", encoding="utf-8") as summary:
        summary.writelines(lines)


def _write_github_output(
    output_path: Path,
    *,
    review_required: bool,
    finding_count: int,
    unactionable_count: int,
    report_digest: str,
) -> None:
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"review_required={'true' if review_required else 'false'}\n")
        output.write(f"finding_count={finding_count}\n")
        output.write(f"unactionable_count={unactionable_count}\n")
        output.write(f"report_digest={report_digest}\n")


def _build_report(
    findings: Sequence[Mapping[str, object]], *, source_ref: str, source_commit: str
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_ref": source_ref,
        "source_commit": source_commit,
        "review_required": bool(findings),
        "finding_count": len(findings),
        "unactionable_count": sum(not bool(finding.get("actionable")) for finding in findings),
        "findings": list(findings),
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    payload["report_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def load_comments(result_path: Path) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("LLM release-safety result is missing or invalid") from error

    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise ValueError("LLM release-safety result did not complete successfully")
    comments = payload.get("comments")
    if not isinstance(comments, Sequence) or isinstance(comments, (str, bytes)):
        raise ValueError("LLM release-safety result has an invalid comments field")
    if not all(isinstance(comment, Mapping) for comment in comments):
        raise ValueError("LLM release-safety result contains an invalid finding")
    return list(comments)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument("--github-step-summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--sanitized-report", type=Path)
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--source-commit", default="")
    args = parser.parse_args()

    try:
        comments = load_comments(args.result)
    except ValueError as error:
        error_message = str(error)
        print(error_message)
        if args.github_annotations:
            title = _escape_workflow_command(
                "LLM public-release review failed", property_value=True
            )
            print(f"::error title={title}::{_escape_workflow_command(error_message)}")
        if args.github_step_summary is not None:
            _write_summary(
                args.github_step_summary,
                findings=(),
                result_error=error_message,
            )
        return 2

    findings = [_sanitize_finding(comment) for comment in comments]
    report = _build_report(
        findings,
        source_ref=args.source_ref,
        source_commit=args.source_commit,
    )
    report_digest = str(report["report_digest"])
    unactionable_count = int(report["unactionable_count"])

    if args.sanitized_report is not None:
        args.sanitized_report.write_text(
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.github_output is not None:
        _write_github_output(
            args.github_output,
            review_required=bool(findings),
            finding_count=len(findings),
            unactionable_count=unactionable_count,
            report_digest=report_digest,
        )

    for index, finding in enumerate(findings, start=1):
        print(
            "LLM public-release sensitivity finding "
            f"{index}: {_display_path(finding.get('path'))}:"
            f"{_display_line(finding.get('start_line'))} "
            f"({finding.get('category', 'other')}/{finding.get('severity', 'unknown')})"
        )
        if args.github_annotations:
            _emit_advisory_annotation(finding)

    if args.github_step_summary is not None:
        _write_summary(
            args.github_step_summary,
            findings=findings,
            report_digest=report_digest,
        )

    if findings:
        print(
            "LLM public-release sensitivity review requires human review of "
            f"{len(findings)} finding(s)"
        )
    else:
        print("LLM public-release sensitivity review produced no findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
