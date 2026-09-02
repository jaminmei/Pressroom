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
    output_path: Path | None = None,
    report_path: Path | None = None,
    source_ref: str = "v0.2.16",
    source_commit: str = "a" * 40,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--result",
        str(result_path),
        "--source-ref",
        source_ref,
        "--source-commit",
        source_commit,
    ]
    if github_annotations:
        command.append("--github-annotations")
    if summary_path is not None:
        command.extend(("--github-step-summary", str(summary_path)))
    if output_path is not None:
        command.extend(("--github-output", str(output_path)))
    if report_path is not None:
        command.extend(("--sanitized-report", str(report_path)))
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_result(path: Path, comments: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"status": "success", "comments": comments}), encoding="utf-8")


def _parse_output(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_empty_result_requires_no_review_and_writes_stable_report(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output.txt"
    report_path = tmp_path / "report.json"
    _write_result(result_path, [])

    result = _run(result_path, output_path=output_path, report_path=report_path)
    output = _parse_output(output_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert result.stdout == "LLM public-release sensitivity review produced no findings\n"
    assert result.stderr == ""
    assert output["review_required"] == "false"
    assert output["finding_count"] == "0"
    assert output["unactionable_count"] == "0"
    assert len(output["report_digest"]) == 64
    assert report == {
        "schema_version": "pressroom-release-sensitivity.v1",
        "source_ref": "v0.2.16",
        "source_commit": "a" * 40,
        "review_required": False,
        "finding_count": 0,
        "unactionable_count": 0,
        "findings": [],
        "report_digest": output["report_digest"],
    }


def test_findings_are_advisory_and_sensitive_model_fields_are_withheld(tmp_path: Path) -> None:
    secret = "do-not-log-this-sensitive-value"
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output.txt"
    report_path = tmp_path / "report.json"
    summary_path = tmp_path / "summary.md"
    _write_result(
        result_path,
        [
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
    )

    result = _run(
        result_path,
        github_annotations=True,
        summary_path=summary_path,
        output_path=output_path,
        report_path=report_path,
    )
    output = _parse_output(output_path)
    report_text = report_path.read_text(encoding="utf-8")
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 0
    assert "app/settings.py:14 (security/critical)" in result.stdout
    assert "::warning file=app/settings.py,line=14" in result.stdout
    assert "::error" not in result.stdout
    assert output["review_required"] == "true"
    assert output["finding_count"] == "1"
    assert "Human review required" in summary
    assert "Approval attests that every finding" in summary
    assert secret not in result.stdout
    assert secret not in summary
    assert secret not in report_text
    assert set(json.loads(report_text)["findings"][0]) == {
        "actionable",
        "category",
        "path",
        "severity",
        "start_line",
    }


def test_every_returned_finding_is_included_for_human_review(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output.txt"
    report_path = tmp_path / "report.json"
    _write_result(
        result_path,
        [
            {
                "path": "app/high.py",
                "start_line": 7,
                "category": " Security ",
                "severity": " HIGH ",
            },
            {
                "path": "app/low.py",
                "start_line": 8,
                "category": "security",
                "severity": "low",
            },
            {
                "path": "app/style.py",
                "start_line": 9,
                "category": "maintainability",
                "severity": "medium",
            },
        ],
    )

    result = _run(result_path, output_path=output_path, report_path=report_path)
    output = _parse_output(output_path)
    findings = json.loads(report_path.read_text(encoding="utf-8"))["findings"]

    assert result.returncode == 0
    assert output["review_required"] == "true"
    assert output["finding_count"] == "3"
    assert [finding["severity"] for finding in findings] == ["high", "low", "medium"]
    assert findings[2]["category"] == "other"


def test_missing_location_is_reported_as_unactionable_advisory(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output.txt"
    report_path = tmp_path / "report.json"
    _write_result(result_path, [{"category": "security", "severity": "high"}])

    result = _run(
        result_path,
        github_annotations=True,
        output_path=output_path,
        report_path=report_path,
    )
    output = _parse_output(output_path)
    finding = json.loads(report_path.read_text(encoding="utf-8"))["findings"][0]

    assert result.returncode == 0
    assert "<unknown path>:? (security/high)" in result.stdout
    assert "::warning title=Public release sensitivity finding::" in result.stdout
    assert "::error" not in result.stdout
    assert output["unactionable_count"] == "1"
    assert finding["path"] is None
    assert finding["start_line"] is None
    assert finding["actionable"] is False


def test_escapes_workflow_command_properties(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    _write_result(
        result_path,
        [
            {
                "path": "app/a,b:c%file.py",
                "start_line": 5,
                "category": "security",
                "severity": "critical",
            }
        ],
    )

    result = _run(result_path, github_annotations=True)

    assert result.returncode == 0
    assert "file=app/a%2Cb%3Ac%25file.py,line=5" in result.stdout


def test_rejects_newline_path_without_reflecting_it(tmp_path: Path) -> None:
    injected_path = "app/file.py\n::error::injected"
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.json"
    _write_result(
        result_path,
        [
            {
                "path": injected_path,
                "start_line": 5,
                "category": "security",
                "severity": "high",
            }
        ],
    )

    result = _run(result_path, github_annotations=True, report_path=report_path)
    report_text = report_path.read_text(encoding="utf-8")

    assert result.returncode == 0
    assert injected_path not in result.stdout
    assert injected_path not in report_text
    assert "::error" not in result.stdout
    assert "lacks an actionable repository path and line" in result.stdout


def test_invalid_result_remains_a_hard_infrastructure_failure(tmp_path: Path) -> None:
    secret = "invalid-result-must-not-be-logged"
    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    output_path = tmp_path / "github-output.txt"
    report_path = tmp_path / "report.json"
    result_path.write_text(f"{{not-json:{secret}}}", encoding="utf-8")

    result = _run(
        result_path,
        github_annotations=True,
        summary_path=summary_path,
        output_path=output_path,
        report_path=report_path,
    )
    summary = summary_path.read_text(encoding="utf-8")

    assert result.returncode == 2
    assert result.stdout.startswith("LLM release-safety result is missing or invalid\n")
    assert "::error title=LLM public-release review failed::" in result.stdout
    assert secret not in result.stdout
    assert secret not in summary
    assert not output_path.exists()
    assert not report_path.exists()
    assert result.stderr == ""


def test_rejects_invalid_comments_structure(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps({"status": "success", "comments": "not-a-list"}), encoding="utf-8"
    )

    result = _run(result_path)

    assert result.returncode == 2
    assert result.stdout == "LLM release-safety result has an invalid comments field\n"


def test_report_digest_is_stable_and_bound_to_source_commit(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    _write_result(
        result_path,
        [
            {
                "path": "app/settings.py",
                "start_line": 14,
                "category": "security",
                "severity": "high",
            }
        ],
    )

    reports = []
    for index, commit in enumerate(("a" * 40, "a" * 40, "b" * 40)):
        report_path = tmp_path / f"report-{index}.json"
        result = _run(result_path, report_path=report_path, source_commit=commit)
        assert result.returncode == 0
        reports.append(json.loads(report_path.read_text(encoding="utf-8")))

    assert reports[0]["report_digest"] == reports[1]["report_digest"]
    assert reports[0]["report_digest"] != reports[2]["report_digest"]
