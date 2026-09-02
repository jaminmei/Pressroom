"""Pi event contract fixture suite: projection safety over shared fixtures.

Consumes the fixture set in ``tests/fixtures/pi_contract`` together with the
frontend assembler contract test (``piContractFixtures.test.ts``). Each
fixture pairs raw (pre-projection) events with index-aligned projected
expectations; ``null`` marks an event the projection must drop entirely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.chatbox_projection import project_event

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "pi_contract"
WORKSPACE_PLACEHOLDER = "${workspace_root}"

FORBIDDEN_KEYS = frozenset(
    {
        "apikey",
        "token",
        "authorization",
        "apikeyheader",
        "credentials",
        "credential",
        "diagnostics",
        "upstreambody",
        "responsebody",
        "rawresponse",
        "internal",
        "sessionfile",
        "extensionsource",
        "sourcepath",
    }
)

FIXTURE_NAMES = sorted(path.stem for path in FIXTURES_ROOT.glob("*.json"))


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_ROOT / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def substitute(value: Any, workspace_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace(WORKSPACE_PLACEHOLDER, str(workspace_root))
    if isinstance(value, list):
        return [substitute(item, workspace_root) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, workspace_root) for key, item in value.items()}
    return value


def assert_no_disallowed_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            canonical_key = "".join(
                character for character in str(key).casefold() if character.isalnum()
            )
            assert canonical_key not in FORBIDDEN_KEYS, f"forbidden key survived projection: {key}"
            assert not (str(key) == "type" and value.get("display") is False), (
                "hidden custom message survived projection"
            )
            assert_no_disallowed_fields(nested)
    elif isinstance(value, list):
        for item in value:
            assert_no_disallowed_fields(item)
    elif isinstance(value, str):
        assert not Path(value).is_absolute(), f"absolute path survived projection: {value}"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_projection_matches_expected_output(name: str, tmp_path: Path) -> None:
    fixture = load_fixture(name)
    raw_events = fixture["raw_events"]
    projected_events = fixture["projected_events"]
    assert len(raw_events) == len(projected_events), "fixture event lists must be index-aligned"

    workspace_root = (tmp_path / "ws").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    for index, (raw, expected) in enumerate(zip(raw_events, projected_events, strict=True)):
        projected = project_event(substitute(raw, workspace_root), workspace_root)
        if expected is None:
            assert projected is None, f"{name}[{index}]: event should be dropped entirely"
            continue
        assert projected is not None, f"{name}[{index}]: event should not be dropped"
        assert projected == expected, f"{name}[{index}]: projection mismatch"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_projected_output_contains_no_disallowed_field(name: str, tmp_path: Path) -> None:
    fixture = load_fixture(name)
    workspace_root = (tmp_path / "ws").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    for raw in fixture["raw_events"]:
        projected = project_event(substitute(raw, workspace_root), workspace_root)
        if projected is None:
            continue
        assert_no_disallowed_fields(projected)


def test_fixture_set_covers_required_cases() -> None:
    required = {
        "streaming-text",
        "thinking",
        "multi-tool",
        "partial-output",
        "failure",
        "abort",
        "retry",
        "compaction",
        "agent-settled",
    }
    assert set(FIXTURE_NAMES) == required


def test_fixtures_record_sdk_provenance() -> None:
    for name in FIXTURE_NAMES:
        provenance = load_fixture(name)["provenance"]
        assert provenance["sdk"]["@earendil-works/pi-coding-agent"] == "0.84.1"
        assert provenance["sources"], f"{name} must record source links"
