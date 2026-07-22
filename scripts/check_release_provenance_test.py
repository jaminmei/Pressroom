from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scripts.check_release_provenance import (
    ProvenanceError,
    validate_merged_push,
    validate_pull_request,
)

REPOSITORY = "jaminmei/Pressroom"
APP_LOGIN = "pressroom-release-sync[bot]"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
MAIN_SHA = "3" * 40
TREE_SHA = "4" * 40
SOURCE_SHA = "5" * 40


def _pull() -> dict[str, Any]:
    return {
        "number": 7,
        "title": "Release v0.2.0 from doc-conv",
        "body": (
            "Publish `v0.2.0` from the validated doc-conv release tag.\n\n"
            f"Source commit: `{SOURCE_SHA}`\n\n"
            f"Source tree: `{TREE_SHA}`\n\n"
            "This PR must pass all PressRoom checks and receive the required approval."
        ),
        "commits": 1,
        "merged_at": None,
        "merge_commit_sha": None,
        "user": {"login": APP_LOGIN},
        "base": {"ref": "main", "sha": BASE_SHA, "repo": {"full_name": REPOSITORY}},
        "head": {
            "ref": "publish/v0.2.0",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
    }


def _commit(sha: str, *, tree: str = TREE_SHA, parent: str = BASE_SHA) -> dict[str, Any]:
    return {
        "sha": sha,
        "parents": [{"sha": parent}],
        "commit": {
            "message": "release: sync v0.2.0 from doc-conv",
            "tree": {"sha": tree},
            "author": {
                "name": "PressRoom Release Sync",
                "email": "pressroom-release-sync@users.noreply.github.com",
            },
            "committer": {
                "name": "PressRoom Release Sync",
                "email": "pressroom-release-sync@users.noreply.github.com",
            },
        },
    }


def test_validates_release_pull_request() -> None:
    provenance = validate_pull_request(
        _pull(),
        _commit(HEAD_SHA),
        expected_repository=REPOSITORY,
        expected_app_login=APP_LOGIN,
    )

    assert provenance.tag == "v0.2.0"
    assert provenance.source_commit == SOURCE_SHA
    assert provenance.source_tree == TREE_SHA
    assert provenance.pull_number == 7


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda pull: pull["user"].update(login="someone-else"), "sync App"),
        (lambda pull: pull["head"].update(ref="feature/release"), "publish/vX.Y.Z"),
        (lambda pull: pull.update(commits=2), "exactly one commit"),
        (lambda pull: pull.update(title="Release something else"), "title"),
        (lambda pull: pull.update(body="No source commit"), "exactly one source commit"),
    ],
)
def test_rejects_invalid_pull_metadata(mutate: Any, message: str) -> None:
    pull = _pull()
    mutate(pull)

    with pytest.raises(ProvenanceError, match=message):
        validate_pull_request(
            pull,
            _commit(HEAD_SHA),
            expected_repository=REPOSITORY,
            expected_app_login=APP_LOGIN,
        )


def test_rejects_release_head_with_wrong_parent() -> None:
    with pytest.raises(ProvenanceError, match="parent"):
        validate_pull_request(
            _pull(),
            _commit(HEAD_SHA, parent="9" * 40),
            expected_repository=REPOSITORY,
            expected_app_login=APP_LOGIN,
        )


def test_rejects_release_head_with_wrong_source_tree_metadata() -> None:
    pull = _pull()
    pull["body"] = pull["body"].replace(TREE_SHA, "8" * 40)

    with pytest.raises(ProvenanceError, match="source tree metadata"):
        validate_pull_request(
            pull,
            _commit(HEAD_SHA),
            expected_repository=REPOSITORY,
            expected_app_login=APP_LOGIN,
        )


def _merged_pull() -> dict[str, Any]:
    pull = _pull()
    pull["merged_at"] = "2026-07-28T00:00:00Z"
    pull["merge_commit_sha"] = MAIN_SHA
    return pull


def test_validates_squash_merge_tree_and_parent() -> None:
    pull = _merged_pull()
    commits = {
        HEAD_SHA: _commit(HEAD_SHA),
        MAIN_SHA: _commit(MAIN_SHA),
    }

    provenance = validate_merged_push(
        MAIN_SHA,
        [pull],
        fetch_pull=lambda number: deepcopy(pull),
        fetch_commit=lambda sha: deepcopy(commits[sha]),
        expected_repository=REPOSITORY,
        expected_app_login=APP_LOGIN,
    )

    assert provenance.tag == "v0.2.0"
    assert provenance.head_commit == HEAD_SHA


@pytest.mark.parametrize(
    ("main_commit", "message"),
    [
        (_commit(MAIN_SHA, tree="8" * 40), "tree"),
        (_commit(MAIN_SHA, parent="8" * 40), "same parent"),
    ],
)
def test_rejects_squash_merge_mismatch(main_commit: dict[str, Any], message: str) -> None:
    pull = _merged_pull()
    commits = {HEAD_SHA: _commit(HEAD_SHA), MAIN_SHA: main_commit}

    with pytest.raises(ProvenanceError, match=message):
        validate_merged_push(
            MAIN_SHA,
            [pull],
            fetch_pull=lambda number: deepcopy(pull),
            fetch_commit=lambda sha: deepcopy(commits[sha]),
            expected_repository=REPOSITORY,
            expected_app_login=APP_LOGIN,
        )


def test_rejects_ambiguous_merged_pull_request() -> None:
    pull = _merged_pull()

    with pytest.raises(ProvenanceError, match="exactly one"):
        validate_merged_push(
            MAIN_SHA,
            [pull, deepcopy(pull)],
            fetch_pull=lambda number: deepcopy(pull),
            fetch_commit=lambda sha: _commit(sha),
            expected_repository=REPOSITORY,
            expected_app_login=APP_LOGIN,
        )
