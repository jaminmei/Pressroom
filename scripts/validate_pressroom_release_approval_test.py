from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("validate_pressroom_release_approval.py")
TAG = "v0.2.16"
COMMIT = "a" * 40


def _write_report(path: Path, *, actionable: bool = True) -> str:
    finding = {
        "actionable": actionable,
        "category": "security",
        "path": "app/settings.py" if actionable else None,
        "severity": "high",
        "start_line": 14 if actionable else None,
    }
    payload: dict[str, object] = {
        "schema_version": "pressroom-release-sensitivity.v1",
        "source_ref": TAG,
        "source_commit": COMMIT,
        "review_required": True,
        "finding_count": 1,
        "unactionable_count": 0 if actionable else 1,
        "findings": [finding],
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload["report_digest"] = digest
    path.write_text(json.dumps(payload), encoding="utf-8")
    return digest


def _run(
    report_path: Path,
    digest: str,
    *,
    permission: str = "admin",
    confirmed: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--report",
        str(report_path),
        "--release-tag",
        TAG,
        "--release-commit",
        COMMIT,
        "--report-digest",
        digest,
        "--actor-permission",
        permission,
    ]
    if confirmed:
        command.append("--confirmed")
    return subprocess.run(command, check=False, capture_output=True, text=True)


def test_accepts_matching_report_and_maintainer_attestation(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path)

    result = _run(report_path, digest, permission="maintain")

    assert result.returncode == 0
    assert result.stdout == (
        "PressRoom release approval accepted for v0.2.16 with 1 reviewed finding(s)\n"
    )
    assert result.stderr == ""


def test_accepts_unactionable_finding_after_explicit_review(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path, actionable=False)

    result = _run(report_path, digest)

    assert result.returncode == 0


def test_rejects_unconfirmed_attestation(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path)

    result = _run(report_path, digest, confirmed=False)

    assert result.returncode == 1
    assert "manual approval attestation was not confirmed" in result.stdout


def test_rejects_actor_without_write_permission(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path)

    result = _run(report_path, digest, permission="read")

    assert result.returncode == 1
    assert "actor lacks permission" in result.stdout


def test_rejects_digest_that_was_not_attested(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    _write_report(report_path)

    result = _run(report_path, "b" * 64)

    assert result.returncode == 1
    assert "digest does not match" in result.stdout


def test_rejects_report_modified_after_generation(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["findings"][0]["start_line"] = 15
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run(report_path, digest)

    assert result.returncode == 1
    assert "digest does not match" in result.stdout


def test_rejects_report_with_raw_model_content(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    digest = _write_report(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["findings"][0]["thinking"] = "must-not-be-retained"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = _run(report_path, digest)

    assert result.returncode == 1
    assert "findings are invalid" in result.stdout
    assert "must-not-be-retained" not in result.stdout
