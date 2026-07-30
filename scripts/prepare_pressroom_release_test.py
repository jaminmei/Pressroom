from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).with_name("prepare_pressroom_release.py")
REPOSITORY = SCRIPT.parent.parent
PRESSROOM_WORKFLOW_SOURCE = ".github/pressroom/ci.yml"
PRESSROOM_WORKFLOW_TARGET = ".github/workflows/ci.yml"
PRESSROOM_WORKFLOW = b"""name: PressRoom Release
on:
  pull_request:
jobs:
  provenance:
    runs-on: ubuntu-latest
"""


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_bytes(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout


def _create_commit(repository: Path, *, include_template: bool = True) -> str:
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "Release test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    files: dict[str, str | bytes] = {
        "AGENTS.md": "# Internal agent directions\n",
        ".claude/commands/review.md": "# Agent command\n",
        ".github/workflows/ci.yml": "name: Public CI\n",
        ".github/workflows/open-code-review.yml": "name: Open Code Review\n",
        "memory/session-bridge.md": "# Internal handoff\n",
        "wiki/hot.md": "# Internal wiki\n",
        "app/main.py": "print('public')\n",
        "tests/unit/test_public_api.py": "def test_public_api():\n    assert True\n",
        "frontend/e2e/public/release.spec.ts": "// Public release coverage\n",
        "frontend/e2e/fixtures/synthetic.txt": "SYNTHETIC PUBLIC FIXTURE\n",
    }
    if include_template:
        files[PRESSROOM_WORKFLOW_SOURCE] = PRESSROOM_WORKFLOW
    for path, content in files.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "release input")
    return _git(repository, "rev-parse", "HEAD")


def _parse_output(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines())


def _workflow_jobs(path: Path) -> set[str]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    return set(jobs)


def test_source_and_pressroom_workflows_have_disjoint_job_sets() -> None:
    source_jobs = _workflow_jobs(REPOSITORY / ".github/workflows/ci.yml")
    pressroom_jobs = _workflow_jobs(REPOSITORY / PRESSROOM_WORKFLOW_SOURCE)

    assert source_jobs == {
        "public-boundary",
        "python-quality",
        "dependency-audit",
        "frontend-quality",
        "standard-compose",
        "full-queue",
        "public-release-llm-review",
        "publish-pressroom",
    }
    assert pressroom_jobs == {
        "public-boundary",
        "release-provenance",
        "finalize-pressroom-release",
    }
    assert "Open Code Review" not in (REPOSITORY / PRESSROOM_WORKFLOW_SOURCE).read_text(
        encoding="utf-8"
    )


def test_filters_pressroom_only_paths_from_release_tree(tmp_path: Path) -> None:
    commit = _create_commit(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repository", str(tmp_path), "--commit", commit],
        check=True,
        capture_output=True,
        text=True,
    )
    trees = _parse_output(result.stdout)
    release_paths = _git(
        tmp_path, "ls-tree", "-r", "--name-only", trees["release_tree"]
    ).splitlines()

    assert trees["source_tree"] != trees["release_tree"]
    assert release_paths == [
        ".github/workflows/ci.yml",
        "app/main.py",
        "frontend/e2e/fixtures/synthetic.txt",
        "frontend/e2e/public/release.spec.ts",
        "tests/unit/test_public_api.py",
    ]
    assert [path for path in release_paths if path.startswith(".github/workflows/")] == [
        PRESSROOM_WORKFLOW_TARGET
    ]

    source_blob = _git(tmp_path, "rev-parse", f"{trees['source_tree']}:{PRESSROOM_WORKFLOW_SOURCE}")
    injected_blob = _git(
        tmp_path, "rev-parse", f"{trees['release_tree']}:{PRESSROOM_WORKFLOW_TARGET}"
    )
    assert injected_blob == source_blob
    assert _git(
        tmp_path,
        "ls-tree",
        trees["release_tree"],
        "--",
        PRESSROOM_WORKFLOW_TARGET,
    ).startswith(f"100644 blob {source_blob}\t")
    assert (
        _git_bytes(tmp_path, "show", f"{trees['release_tree']}:{PRESSROOM_WORKFLOW_TARGET}")
        == PRESSROOM_WORKFLOW
    )
    assert _git_bytes(tmp_path, "show", f"{trees['release_tree']}:app/main.py") == (
        b"print('public')\n"
    )


def test_release_tree_is_deterministic(tmp_path: Path) -> None:
    commit = _create_commit(tmp_path)

    command = [
        sys.executable,
        str(SCRIPT),
        "--repository",
        str(tmp_path),
        "--commit",
        commit,
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert first.stdout == second.stdout
    assert (
        _parse_output(first.stdout)["release_tree"] == _parse_output(second.stdout)["release_tree"]
    )


def test_fails_when_pressroom_workflow_template_is_missing(tmp_path: Path) -> None:
    commit = _create_commit(tmp_path, include_template=False)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repository", str(tmp_path), "--commit", commit],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip() == "could not prepare the PressRoom release tree"


@pytest.mark.parametrize("mode", ["100755", "120000"])
def test_fails_when_pressroom_workflow_template_is_not_100644(tmp_path: Path, mode: str) -> None:
    _create_commit(tmp_path)
    template_blob = _git(tmp_path, "rev-parse", f"HEAD:{PRESSROOM_WORKFLOW_SOURCE}")
    _git(
        tmp_path,
        "update-index",
        "--cacheinfo",
        f"{mode},{template_blob},{PRESSROOM_WORKFLOW_SOURCE}",
    )
    _git(tmp_path, "commit", "-m", f"make template mode {mode}")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repository", str(tmp_path), "--commit", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stderr.strip() == "could not prepare the PressRoom release tree"


def test_fails_closed_on_invalid_git_commit(tmp_path: Path) -> None:
    _create_commit(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repository",
            str(tmp_path),
            "--commit",
            "missing-commit",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip() == "could not prepare the PressRoom release tree"
