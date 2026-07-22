#!/usr/bin/env python3
"""Fail on production npm advisories except narrowly approved, expiring exceptions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

APPROVED_ADVISORIES = {
    "https://github.com/advisories/GHSA-qwww-vcr4-c8h2": {
        "expires": dt.date(2026, 9, 30),
        "reason": "React Router RSC mode is not used by the Vite SPA frontend",
    },
}
BLOCKING_SEVERITIES = {"high", "critical"}


def _advisory_urls(
    package: str,
    vulnerabilities: dict[str, Any],
    *,
    visiting: frozenset[str] = frozenset(),
) -> set[str]:
    if package in visiting:
        return set()
    vulnerability = vulnerabilities.get(package)
    if not isinstance(vulnerability, dict):
        return set()
    urls: set[str] = set()
    for cause in vulnerability.get("via", []):
        if isinstance(cause, dict):
            url = cause.get("url")
            if isinstance(url, str):
                urls.add(url)
        elif isinstance(cause, str):
            urls.update(
                _advisory_urls(
                    cause,
                    vulnerabilities,
                    visiting=visiting | {package},
                )
            )
    return urls


def _audit(frontend: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["npm", "audit", "--omit=dev", "--json"],
        cwd=frontend,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("npm audit did not return valid JSON") from error
    if not isinstance(report, dict) or report.get("error"):
        raise RuntimeError("npm audit failed before producing a vulnerability report")
    if result.returncode not in {0, 1}:
        raise RuntimeError("npm audit exited unexpectedly")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend", type=Path)
    args = parser.parse_args()

    today = dt.date.today()
    expired = [url for url, approval in APPROVED_ADVISORIES.items() if today > approval["expires"]]
    if expired:
        for url in expired:
            print(f"FRONTEND AUDIT: approved exception expired: {url}")
        return 1

    try:
        report = _audit(args.frontend)
    except RuntimeError as error:
        print(f"FRONTEND AUDIT: {error}")
        return 1

    vulnerabilities = report.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        print("FRONTEND AUDIT: vulnerability report has an invalid shape")
        return 1

    observed: set[str] = set()
    failures: list[tuple[str, set[str]]] = []
    for package, vulnerability in vulnerabilities.items():
        if not isinstance(vulnerability, dict):
            failures.append((package, set()))
            continue
        if vulnerability.get("severity") not in BLOCKING_SEVERITIES:
            continue
        urls = _advisory_urls(package, vulnerabilities)
        observed.update(urls)
        if not urls or not urls.issubset(APPROVED_ADVISORIES):
            failures.append((package, urls))

    if failures:
        for package, urls in failures:
            details = ", ".join(sorted(urls)) if urls else "unknown advisory"
            print(f"FRONTEND AUDIT: blocking production vulnerability in {package}: {details}")
        return 1

    unused = set(APPROVED_ADVISORIES) - observed
    if unused:
        for url in sorted(unused):
            print(f"FRONTEND AUDIT: exception is no longer needed; remove it: {url}")
        return 1

    for url in sorted(observed):
        approval = APPROVED_ADVISORIES[url]
        print(
            "Frontend production audit passed with approved exception: "
            f"{url} ({approval['reason']}; expires {approval['expires'].isoformat()})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
