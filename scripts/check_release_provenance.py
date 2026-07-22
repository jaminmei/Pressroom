#!/usr/bin/env python3
"""Validate that a PressRoom release PR and its squash merge came from the sync App."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
BRANCH_PATTERN = re.compile(r"publish/(v[0-9]+\.[0-9]+\.[0-9]+)")
SOURCE_COMMIT_PATTERN = re.compile(r"(?m)^Source commit: `([0-9a-f]{40})`$")
SOURCE_TREE_PATTERN = re.compile(r"(?m)^Source tree: `([0-9a-f]{40})`$")
EXPECTED_COMMIT_AUTHOR = {
    "name": "PressRoom Release Sync",
    "email": "pressroom-release-sync@users.noreply.github.com",
}


class ProvenanceError(RuntimeError):
    """Raised when release provenance is missing or inconsistent."""


@dataclass(frozen=True)
class Provenance:
    tag: str
    source_commit: str
    source_tree: str
    pull_number: int
    head_commit: str


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProvenanceError(f"{label} is missing or invalid")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProvenanceError(f"{label} is missing or invalid")
    return value


def _repository_name(side: dict[str, Any], label: str) -> str:
    repository = _mapping(side.get("repo"), f"{label} repository")
    return _string(repository.get("full_name"), f"{label} repository name")


def _pull_metadata(
    pull: dict[str, Any],
    *,
    expected_repository: str,
    expected_app_login: str,
) -> tuple[str, str, str, str]:
    base = _mapping(pull.get("base"), "pull request base")
    head = _mapping(pull.get("head"), "pull request head")
    user = _mapping(pull.get("user"), "pull request author")

    if _string(base.get("ref"), "base branch") != "main":
        raise ProvenanceError("release pull request must target main")
    if _repository_name(base, "base") != expected_repository:
        raise ProvenanceError("release pull request base repository is unexpected")
    if _repository_name(head, "head") != expected_repository:
        raise ProvenanceError("release pull request head must be in PressRoom")
    if _string(user.get("login"), "pull request author login") != expected_app_login:
        raise ProvenanceError("release pull request was not opened by the sync App")

    branch = _string(head.get("ref"), "release branch")
    branch_match = BRANCH_PATTERN.fullmatch(branch)
    if branch_match is None:
        raise ProvenanceError("release branch must match publish/vX.Y.Z")
    tag = branch_match.group(1)
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ProvenanceError("release tag is not a semantic version")

    if _string(pull.get("title"), "pull request title") != f"Release {tag} from doc-conv":
        raise ProvenanceError("release pull request title does not match its tag")
    body = _string(pull.get("body"), "pull request body")
    source_matches = SOURCE_COMMIT_PATTERN.findall(body)
    if len(source_matches) != 1:
        raise ProvenanceError("release pull request must name exactly one source commit")
    tree_matches = SOURCE_TREE_PATTERN.findall(body)
    if len(tree_matches) != 1:
        raise ProvenanceError("release pull request must name exactly one source tree")

    return (
        tag,
        source_matches[0],
        tree_matches[0],
        _string(head.get("sha"), "pull request head SHA"),
    )


def _commit_details(commit: dict[str, Any], *, label: str) -> tuple[str, str, list[str]]:
    sha = _string(commit.get("sha"), f"{label} SHA")
    details = _mapping(commit.get("commit"), f"{label} details")
    tree = _mapping(details.get("tree"), f"{label} tree")
    parents_raw = commit.get("parents")
    if not isinstance(parents_raw, list):
        raise ProvenanceError(f"{label} parents are missing or invalid")
    parents = [
        _string(_mapping(parent, f"{label} parent").get("sha"), f"{label} parent SHA")
        for parent in parents_raw
    ]
    return sha, _string(tree.get("sha"), f"{label} tree SHA"), parents


def _validate_sync_commit(commit: dict[str, Any], *, tag: str, expected_sha: str) -> None:
    sha, _, _ = _commit_details(commit, label="release head commit")
    if sha != expected_sha:
        raise ProvenanceError("release head commit does not match the pull request head")

    details = _mapping(commit.get("commit"), "release head commit details")
    if _string(details.get("message"), "release head commit message") != (
        f"release: sync {tag} from doc-conv"
    ):
        raise ProvenanceError("release head commit message does not match its tag")
    for field in ("author", "committer"):
        identity = _mapping(details.get(field), f"release head commit {field}")
        for key, expected in EXPECTED_COMMIT_AUTHOR.items():
            if _string(identity.get(key), f"release head commit {field} {key}") != expected:
                raise ProvenanceError(f"release head commit {field} identity is unexpected")


def validate_pull_request(
    pull: dict[str, Any],
    head_commit: dict[str, Any],
    *,
    expected_repository: str,
    expected_app_login: str,
) -> Provenance:
    tag, source_commit, source_tree, head_sha = _pull_metadata(
        pull,
        expected_repository=expected_repository,
        expected_app_login=expected_app_login,
    )
    if pull.get("commits") != 1:
        raise ProvenanceError("release pull request must contain exactly one commit")

    base = _mapping(pull.get("base"), "pull request base")
    base_sha = _string(base.get("sha"), "pull request base SHA")
    _validate_sync_commit(head_commit, tag=tag, expected_sha=head_sha)
    _, head_tree, parents = _commit_details(head_commit, label="release head commit")
    if parents != [base_sha]:
        raise ProvenanceError("release head commit parent must equal the pull request base")
    if head_tree != source_tree:
        raise ProvenanceError("release head commit tree does not match the source tree metadata")

    number = pull.get("number")
    if not isinstance(number, int) or number <= 0:
        raise ProvenanceError("pull request number is missing or invalid")
    return Provenance(tag, source_commit, source_tree, number, head_sha)


def validate_merged_push(
    main_sha: str,
    associated_pulls: list[object],
    *,
    fetch_pull: Callable[[int], dict[str, Any]],
    fetch_commit: Callable[[str], dict[str, Any]],
    expected_repository: str,
    expected_app_login: str,
) -> Provenance:
    candidates: list[dict[str, Any]] = []
    for pull in associated_pulls:
        if not isinstance(pull, dict):
            continue
        if pull.get("merged_at") and pull.get("merge_commit_sha") == main_sha:
            candidates.append(pull)
    if len(candidates) != 1:
        raise ProvenanceError(
            "main push must correspond to exactly one merged release pull request"
        )

    number = candidates[0].get("number")
    if not isinstance(number, int) or number <= 0:
        raise ProvenanceError("merged pull request number is missing or invalid")
    pull = fetch_pull(number)
    if pull.get("merged_at") is None or pull.get("merge_commit_sha") != main_sha:
        raise ProvenanceError("merged pull request does not match the main commit")

    tag, source_commit, source_tree, head_sha = _pull_metadata(
        pull,
        expected_repository=expected_repository,
        expected_app_login=expected_app_login,
    )
    if pull.get("commits") != 1:
        raise ProvenanceError("merged release pull request must contain exactly one commit")

    head_commit = fetch_commit(head_sha)
    main_commit = fetch_commit(main_sha)
    _validate_sync_commit(head_commit, tag=tag, expected_sha=head_sha)
    _, head_tree, head_parents = _commit_details(head_commit, label="release head commit")
    resolved_main_sha, main_tree, main_parents = _commit_details(
        main_commit, label="squash merge commit"
    )
    if resolved_main_sha != main_sha:
        raise ProvenanceError("resolved main commit does not match the push SHA")
    if len(head_parents) != 1 or head_parents != main_parents:
        raise ProvenanceError("squash merge and release head must share the same parent")
    if head_tree != main_tree:
        raise ProvenanceError("squash merge tree does not match the checked release tree")
    if head_tree != source_tree:
        raise ProvenanceError("release head commit tree does not match the source tree metadata")

    return Provenance(tag, source_commit, source_tree, number, head_sha)


class GitHubApi:
    def __init__(self, api_url: str, repository: str, token: str) -> None:
        self.base_url = f"{api_url}/repos/{repository}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str) -> object:
        request = urllib.request.Request(
            f"{self.base_url}{path}", headers=self.headers, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ProvenanceError("GitHub provenance API request failed") from error

    def get_mapping(self, path: str) -> dict[str, Any]:
        return _mapping(self.get(path), "GitHub API response")


def _write_outputs(provenance: Provenance) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path is None:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"tag={provenance.tag}\n")
        output.write(f"source_commit={provenance.source_commit}\n")
        output.write(f"source_tree={provenance.source_tree}\n")
        output.write(f"pull_number={provenance.pull_number}\n")
        output.write(f"head_commit={provenance.head_commit}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--expected-repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--expected-app-login", default="pressroom-release-sync[bot]")
    args = parser.parse_args()

    if args.event_file is None or not args.expected_repository:
        raise SystemExit("release provenance environment is incomplete")
    event = _mapping(json.loads(args.event_file.read_text(encoding="utf-8")), "event payload")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    token = os.environ.get("GH_TOKEN", "")
    api_url = os.environ.get("GITHUB_API_URL", "")
    if not token or not api_url:
        raise SystemExit("release provenance API credentials are missing")
    api = GitHubApi(api_url, args.expected_repository, token)

    try:
        if event_name == "pull_request":
            pull = _mapping(event.get("pull_request"), "pull request event")
            head = _mapping(pull.get("head"), "pull request head")
            head_sha = _string(head.get("sha"), "pull request head SHA")
            provenance = validate_pull_request(
                pull,
                api.get_mapping(f"/commits/{urllib.parse.quote(head_sha, safe='')}"),
                expected_repository=args.expected_repository,
                expected_app_login=args.expected_app_login,
            )
        elif event_name == "push" and os.environ.get("GITHUB_REF") == "refs/heads/main":
            main_sha = _string(os.environ.get("GITHUB_SHA"), "main push SHA")
            pulls = api.get(f"/commits/{urllib.parse.quote(main_sha, safe='')}/pulls")
            if not isinstance(pulls, list):
                raise ProvenanceError("associated pull request response is invalid")
            provenance = validate_merged_push(
                main_sha,
                pulls,
                fetch_pull=lambda number: api.get_mapping(f"/pulls/{number}"),
                fetch_commit=lambda sha: api.get_mapping(
                    f"/commits/{urllib.parse.quote(sha, safe='')}"
                ),
                expected_repository=args.expected_repository,
                expected_app_login=args.expected_app_login,
            )
        else:
            raise ProvenanceError("release provenance only supports PressRoom PRs and main pushes")
    except ProvenanceError as error:
        print(f"RELEASE PROVENANCE: {error}")
        return 1

    _write_outputs(provenance)
    print(f"Release provenance passed: {provenance.tag} via PR #{provenance.pull_number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
