from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("prepare_pressroom_release.py")


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _create_commit(repository: Path) -> str:
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "Release test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    for path, content in {
        "AGENTS.md": "# Internal agent directions\n",
        ".claude/commands/review.md": "# Agent command\n",
        "memory/session-bridge.md": "# Internal handoff\n",
        "wiki/hot.md": "# Internal wiki\n",
        "app/main.py": "print('public')\n",
        "tests/unit/test_public_api.py": "def test_public_api():\n    assert True\n",
        "frontend/e2e/public/release.spec.ts": "// Public release coverage\n",
        "frontend/e2e/fixtures/synthetic.txt": "SYNTHETIC PUBLIC FIXTURE\n",
    }.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "release input")
    return _git(repository, "rev-parse", "HEAD")


def _parse_output(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines())


def test_filters_agent_and_development_knowledge_from_release_tree(tmp_path: Path) -> None:
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
        "app/main.py",
        "frontend/e2e/fixtures/synthetic.txt",
        "frontend/e2e/public/release.spec.ts",
        "tests/unit/test_public_api.py",
    ]


def test_keeps_the_original_tree_when_no_excluded_paths_exist(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Release test")
    _git(tmp_path, "config", "user.email", "release-test@example.invalid")
    app = tmp_path / "app/main.py"
    app.parent.mkdir(parents=True)
    app.write_text("print('public')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "public release input")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repository", str(tmp_path), "--commit", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    trees = _parse_output(result.stdout)

    assert trees["source_tree"] == trees["release_tree"]
