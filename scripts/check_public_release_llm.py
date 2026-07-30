#!/usr/bin/env python3
"""Fail a public release when its dedicated LLM review reports a finding.

The OCR JSON result can contain source snippets and model reasoning. This gate
deliberately emits only controlled annotations and summaries so a failed release
remains actionable without adding sensitive material to CI logs.
"""

from __future__ import annotations

import argparse
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BLOCKING_CATEGORY = "security"
BLOCKING_SEVERITIES = frozenset({"critical", "high"})
ANNOTATION_TITLE = "Public release sensitivity finding"
ANNOTATION_MESSAGE = (
    "Potential release-sensitive information: inspect this line for a literal "
    "credential, private endpoint or data, internal-only information, or private "
    "source. Raw model text is withheld."
)


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


def _is_blocking(comment: Mapping[str, Any]) -> bool:
    return (
        _normalize_label(comment.get("category")) == BLOCKING_CATEGORY
        and _normalize_label(comment.get("severity")) in BLOCKING_SEVERITIES
    )


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


def _escape_workflow_command(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def _summary_path(value: object) -> str:
    return html.escape(_display_path(value), quote=True).replace("|", "&#124;")


def _emit_blocking_annotation(comment: Mapping[str, Any]) -> None:
    path = _annotation_path(comment.get("path"))
    line = _line_number(comment.get("start_line"))
    title = _escape_workflow_command(ANNOTATION_TITLE, property_value=True)
    message = _escape_workflow_command(ANNOTATION_MESSAGE)
    if path is None or line is None:
        print(
            f"::error title={title}::Blocking security finding lacks an actionable "
            "repository path and line. Raw model text is withheld."
        )
        return
    annotation_path = _escape_workflow_command(path, property_value=True)
    print(f"::error file={annotation_path},line={line},title={title}::{message}")


def _write_summary(
    summary_path: Path,
    *,
    blockers: Sequence[Mapping[str, Any]],
    ignored_count: int,
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
        status = "Blocked" if blockers else "Passed"
        lines_list = [
            "## LLM public-release sensitivity review\n\n",
            f"**Status:** {status}\n\n",
            f"Blocking security findings: **{len(blockers)}**  \n",
            f"Ignored out-of-policy findings: **{ignored_count}**\n\n",
        ]
        if blockers:
            lines_list.extend(
                (
                    "| File | Line | Category | Severity | Error |\n",
                    "| --- | ---: | --- | --- | --- |\n",
                )
            )
            for comment in blockers:
                category = _normalize_label(comment.get("category")) or "unknown"
                severity = _normalize_label(comment.get("severity")) or "unknown"
                lines_list.append(
                    "| "
                    f"{_summary_path(comment.get('path'))} | "
                    f"{_display_line(comment.get('start_line'))} | "
                    f"{category} | "
                    f"{severity} | "
                    "Potential release-sensitive information; inspect the referenced "
                    "source line. |\n"
                )
            lines_list.append("\nRaw model text and source snippets are intentionally withheld.\n")
        lines = tuple(lines_list)
    with summary_path.open("a", encoding="utf-8") as summary:
        summary.writelines(lines)


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
                blockers=(),
                ignored_count=0,
                result_error=error_message,
            )
        return 2

    blockers = [comment for comment in comments if _is_blocking(comment)]
    ignored_count = len(comments) - len(blockers)

    if ignored_count:
        print(
            "LLM public-release sensitivity review ignored "
            f"{ignored_count} out-of-policy finding(s)"
        )
        if args.github_annotations:
            title = _escape_workflow_command(
                "Ignored out-of-policy LLM findings", property_value=True
            )
            print(
                f"::warning title={title}::Ignored {ignored_count} finding(s) that "
                "were not explicitly security/high or security/critical."
            )

    for index, comment in enumerate(blockers, start=1):
        category = _normalize_label(comment.get("category")) or "unknown"
        severity = _normalize_label(comment.get("severity")) or "unknown"
        print(
            "LLM public-release sensitivity finding "
            f"{index}: {_display_path(comment.get('path'))}:"
            f"{_display_line(comment.get('start_line'))} "
            f"({category}/{severity})"
        )
        if args.github_annotations:
            _emit_blocking_annotation(comment)

    if args.github_step_summary is not None:
        _write_summary(
            args.github_step_summary,
            blockers=blockers,
            ignored_count=ignored_count,
        )

    if not blockers:
        print("LLM public-release sensitivity review passed")
        return 0

    print("LLM public-release sensitivity review blocked the PressRoom sync")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
