#!/usr/bin/env python3
"""Validate a manual PressRoom release-sensitivity approval attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

REPORT_SCHEMA_VERSION = "pressroom-release-sensitivity.v1"
ALLOWED_PERMISSIONS = frozenset({"admin", "maintain", "write"})
ALLOWED_FINDING_KEYS = frozenset({"actionable", "category", "path", "severity", "start_line"})
ALLOWED_CATEGORIES = frozenset({"security", "other"})
ALLOWED_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info", "unknown"})
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class ApprovalError(ValueError):
    """Raised when a manual release approval cannot be trusted."""


def _load_report(path: Path) -> Mapping[str, object]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ApprovalError("sanitized sensitivity report is missing or invalid") from error
    if not isinstance(report, Mapping):
        raise ApprovalError("sanitized sensitivity report has an invalid structure")
    return report


def _validate_finding(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != ALLOWED_FINDING_KEYS:
        return False
    path = value.get("path")
    line = value.get("start_line")
    actionable = value.get("actionable")
    return (
        (path is None or isinstance(path, str))
        and (line is None or (isinstance(line, int) and not isinstance(line, bool) and line > 0))
        and isinstance(actionable, bool)
        and actionable == (isinstance(path, str) and isinstance(line, int))
        and value.get("category") in ALLOWED_CATEGORIES
        and value.get("severity") in ALLOWED_SEVERITIES
    )


def validate_approval(
    report_path: Path,
    *,
    release_tag: str,
    release_commit: str,
    expected_digest: str,
    actor_permission: str,
    confirmed: bool,
) -> Mapping[str, object]:
    if not confirmed:
        raise ApprovalError("manual approval attestation was not confirmed")
    if actor_permission not in ALLOWED_PERMISSIONS:
        raise ApprovalError("workflow actor lacks permission to approve a release")
    if TAG_PATTERN.fullmatch(release_tag) is None:
        raise ApprovalError("release tag is invalid")
    if COMMIT_PATTERN.fullmatch(release_commit) is None:
        raise ApprovalError("release commit is invalid")
    if DIGEST_PATTERN.fullmatch(expected_digest) is None:
        raise ApprovalError("sensitivity report digest is invalid")

    report = _load_report(report_path)
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ApprovalError("sanitized sensitivity report schema is invalid")
    if report.get("source_ref") != release_tag or report.get("source_commit") != release_commit:
        raise ApprovalError("sensitivity report does not match the release tag and commit")
    if report.get("review_required") is not True:
        raise ApprovalError("manual approval is only valid for a report that requires review")

    findings = report.get("findings")
    if (
        not isinstance(findings, Sequence)
        or isinstance(findings, (str, bytes))
        or not findings
        or not all(_validate_finding(finding) for finding in findings)
    ):
        raise ApprovalError("sanitized sensitivity report findings are invalid")
    if report.get("finding_count") != len(findings):
        raise ApprovalError("sanitized sensitivity report finding count is invalid")
    unactionable_count = sum(not bool(finding.get("actionable")) for finding in findings)
    if report.get("unactionable_count") != unactionable_count:
        raise ApprovalError("sanitized sensitivity report location count is invalid")

    report_digest = report.get("report_digest")
    if not isinstance(report_digest, str) or not DIGEST_PATTERN.fullmatch(report_digest):
        raise ApprovalError("sanitized sensitivity report digest is invalid")
    canonical_payload = dict(report)
    del canonical_payload["report_digest"]
    canonical = json.dumps(
        canonical_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    computed_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if report_digest != computed_digest or report_digest != expected_digest:
        raise ApprovalError("sensitivity report digest does not match the approved report")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--release-commit", required=True)
    parser.add_argument("--report-digest", required=True)
    parser.add_argument("--actor-permission", required=True)
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()

    try:
        report = validate_approval(
            args.report,
            release_tag=args.release_tag,
            release_commit=args.release_commit,
            expected_digest=args.report_digest,
            actor_permission=args.actor_permission,
            confirmed=args.confirmed,
        )
    except ApprovalError as error:
        print(f"PressRoom release approval rejected: {error}")
        return 1

    print(
        "PressRoom release approval accepted for "
        f"{args.release_tag} with {report['finding_count']} reviewed finding(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
