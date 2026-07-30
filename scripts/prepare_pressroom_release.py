#!/usr/bin/env python3
"""Build the filtered Git tree that may be synchronized to PressRoom."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

PRESSROOM_WORKFLOW_SOURCE = ".github/pressroom/ci.yml"
PRESSROOM_WORKFLOW_TARGET = ".github/workflows/ci.yml"

EXCLUDED_RELEASE_PATHS = (
    "AGENTS.md",
    ".claude",
    ".github/workflows",
    PRESSROOM_WORKFLOW_SOURCE,
    "memory",
    "wiki",
)


def _git(
    repository: Path,
    *args: str,
    input_data: bytes | None = None,
    environment: dict[str, str] | None = None,
) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        input=input_data,
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("could not prepare the PressRoom release tree")
    return result.stdout


def _pressroom_workflow_blob(repository: Path, source_tree: str) -> str:
    entry = _git(
        repository,
        "ls-tree",
        "-z",
        "--full-tree",
        source_tree,
        "--",
        PRESSROOM_WORKFLOW_SOURCE,
    )
    entries = entry.split(b"\0")
    if len(entries) != 2 or entries[-1] or not entries[0]:
        raise RuntimeError("could not prepare the PressRoom release tree")

    try:
        metadata, path = entries[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
        workflow_blob = object_id.decode("ascii")
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("could not prepare the PressRoom release tree") from error

    if mode != b"100644" or object_type != b"blob" or path != PRESSROOM_WORKFLOW_SOURCE.encode():
        raise RuntimeError("could not prepare the PressRoom release tree")

    _git(repository, "cat-file", "-e", f"{workflow_blob}^{{blob}}")
    return workflow_blob


def build_release_tree(repository: Path, commit: str) -> tuple[str, str]:
    source_commit = _git(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{commit}^{{commit}}",
    )
    source_tree = _git(repository, "rev-parse", f"{source_commit.decode().strip()}^{{tree}}")
    source_tree_sha = source_tree.decode().strip()
    workflow_blob = _pressroom_workflow_blob(repository, source_tree_sha)

    descriptor, index_name = tempfile.mkstemp(prefix="pressroom-release-index-")
    os.close(descriptor)
    index_path = Path(index_name)
    index_path.unlink()
    environment = os.environ.copy()
    environment["GIT_INDEX_FILE"] = str(index_path)
    try:
        _git(repository, "read-tree", source_tree_sha, environment=environment)
        paths = _git(
            repository,
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            source_tree_sha,
            "--",
            *EXCLUDED_RELEASE_PATHS,
        )
        if paths:
            _git(
                repository,
                "update-index",
                "--force-remove",
                "-z",
                "--stdin",
                input_data=paths,
                environment=environment,
            )
        _git(
            repository,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{workflow_blob},{PRESSROOM_WORKFLOW_TARGET}",
            environment=environment,
        )
        release_tree = _git(repository, "write-tree", environment=environment).decode().strip()
    finally:
        index_path.unlink(missing_ok=True)

    return source_tree_sha, release_tree


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        source_tree, release_tree = build_release_tree(args.repository.resolve(), args.commit)
    except (OSError, RuntimeError) as error:
        raise SystemExit("could not prepare the PressRoom release tree") from error

    lines = (f"source_tree={source_tree}\n", f"release_tree={release_tree}\n")
    if args.github_output is None:
        print("".join(lines), end="")
    else:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.writelines(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
