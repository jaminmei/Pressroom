from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_public_release_llm.py")


def _run(
    result_path: Path,
    *,
    github_annotations: bool = False,
    summary_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--result", str(result_path)]
    if github_annotations:
        command.append("--github-annotations")
    if summary_path is not None:
        command.extend(("--github-step-summary", str(summary_path)))
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def test_accepts_an_empty_successful_result(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps({"status": "success", "comments": []}), encoding="utf-8")

    result = _run(result_path)

    assert result.returncode == 0
    assert result.stdout == "LLM public-release sensitivity review passed\n"
    assert result.stderr == ""


def test_blocks_findings_with_safe_annotations_and_summary(tmp_path: Path) -> None:
    secret = "do-not-log-this-sensitive-value"
    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/settings.py",
                        "start_line": 14,
                        "content": secret,
                        "existing_code": secret,
                        "thinking": secret,
                        "category": "security",
                        "severity": "critical",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        result_path,
        github_annotations=True,
        summary_path=summary_path,
    )
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "app/settings.py:14 (security/critical)" in result.stdout
    assert "::error file=app/settings.py,line=14" in result.stdout
    assert "Potential release-sensitive information" in result.stdout
    assert "app/settings.py" in summary
    assert "Potential release-sensitive information" in summary
    assert secret not in result.stdout
    assert secret not in summary
    assert result.stderr == ""


def test_blocks_case_insensitive_high_security_finding(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/config.py",
                        "start_line": 9,
                        "category": " Security ",
                        "severity": " HIGH ",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(result_path)

    assert result.returncode == 1
    assert "app/config.py:9 (security/high)" in result.stdout


def test_ignores_non_security_and_low_severity_findings(tmp_path: Path) -> None:
    secret = "ignored-finding-sensitive-value"
    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/maintainability.py",
                        "start_line": 4,
                        "category": "maintainability",
                        "severity": "medium",
                        "content": secret,
                    },
                    {
                        "path": "app/low.py",
                        "start_line": 8,
                        "category": "security",
                        "severity": "low",
                        "content": secret,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        result_path,
        github_annotations=True,
        summary_path=summary_path,
    )
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 0
    assert "ignored 2 out-of-policy finding(s)" in result.stdout
    assert "::warning title=Ignored out-of-policy LLM findings::" in result.stdout
    assert "LLM public-release sensitivity review passed" in result.stdout
    assert "Blocking security findings: **0**" in summary
    assert "Ignored out-of-policy findings: **2**" in summary
    assert "app/maintainability.py" not in result.stdout
    assert "app/maintainability.py" not in summary
    assert secret not in result.stdout
    assert secret not in summary


def test_mixed_findings_only_display_blocking_security_findings(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/style.py",
                        "start_line": 3,
                        "category": "maintainability",
                        "severity": "low",
                    },
                    {
                        "path": "app/private.py",
                        "start_line": 17,
                        "category": "security",
                        "severity": "high",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(result_path, summary_path=summary_path)
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "ignored 1 out-of-policy finding(s)" in result.stdout
    assert "app/private.py:17 (security/high)" in result.stdout
    assert "app/style.py" not in result.stdout
    assert "app/private.py" in summary
    assert "app/style.py" not in summary


def test_missing_location_uses_job_level_error_and_still_blocks(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {"category": "security", "severity": "high"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(result_path, github_annotations=True)

    assert result.returncode == 1
    assert "<unknown path>:? (security/high)" in result.stdout
    assert "::error title=Public release sensitivity finding::" in result.stdout
    assert "lacks an actionable repository path and line" in result.stdout
    assert "::error file=" not in result.stdout


def test_escapes_workflow_command_properties(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/a,b:c%file.py",
                        "start_line": 5,
                        "category": "security",
                        "severity": "critical",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(result_path, github_annotations=True)

    assert result.returncode == 1
    assert "file=app/a%2Cb%3Ac%25file.py,line=5" in result.stdout


def test_rejects_newline_path_as_non_actionable(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "success",
                "comments": [
                    {
                        "path": "app/file.py\n::warning::injected",
                        "start_line": 5,
                        "category": "security",
                        "severity": "high",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run(result_path, github_annotations=True)

    assert result.returncode == 1
    assert "::error file=" not in result.stdout
    assert "\n::warning::injected\n" not in result.stdout
    assert "lacks an actionable repository path and line" in result.stdout


def test_rejects_invalid_result_without_echoing_its_contents(tmp_path: Path) -> None:
    secret = "invalid-result-must-not-be-logged"
    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    result_path.write_text(f"{{not-json:{secret}}}", encoding="utf-8")

    result = _run(
        result_path,
        github_annotations=True,
        summary_path=summary_path,
    )
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 2
    assert result.stdout.startswith("LLM release-safety result is missing or invalid\n")
    assert "::error title=LLM public-release review failed::" in result.stdout
    assert secret not in result.stdout
    assert secret not in summary
    assert result.stderr == ""


def test_rejects_invalid_comments_structure(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps({"status": "success", "comments": "not-a-list"}),
        encoding="utf-8",
    )

    result = _run(result_path)

    assert result.returncode == 2
    assert result.stdout == "LLM release-safety result has an invalid comments field\n"
