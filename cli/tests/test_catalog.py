from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

import yaml
from pressroom_cli.catalog import executor_catalog, load_catalog


def test_packaged_catalog_matches_canonical_source() -> None:
    cli_root = Path(__file__).resolve().parents[1]
    canonical_path = cli_root / "catalog" / "tool-catalog.yaml"
    packaged_path = cli_root / "pressroom_cli" / "tool-catalog.yaml"
    canonical = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))

    assert load_catalog() == canonical
    assert packaged_path.read_bytes() == canonical_path.read_bytes()


def test_packaged_contracts_match_canonical_source() -> None:
    cli_root = Path(__file__).resolve().parents[1]

    assert (cli_root / "pressroom_cli" / "cli-contracts.yaml").read_bytes() == (
        cli_root / "catalog" / "cli-contracts.yaml"
    ).read_bytes()


def test_catalog_has_expected_business_tool_counts() -> None:
    payload = load_catalog()
    commands = payload["commands"]
    ready = [item for item in commands if item["status"] == "cli-ready"]
    deferred = [item for item in commands if item["status"] == "deferred"]

    assert len(commands) == 66
    assert len(ready) == 63
    assert len(deferred) == 3
    assert sum(item["exposure"] == "agent-default" for item in ready) == 38
    assert sum(item["exposure"] == "agent-confirmation" for item in ready) == 25


def test_executor_catalog_contains_only_ready_business_tools() -> None:
    commands = executor_catalog()["commands"]
    excluded_roots = {"auth", "config", "workspace", "doctor", "commands"}

    assert len(commands) == 63
    assert {item["status"] for item in commands} == {"cli-ready"}
    assert {item["exposure"] for item in commands} <= {
        "agent-default",
        "agent-confirmation",
    }
    assert not {item["command"].split()[1] for item in commands} & excluded_roots


def test_workflow_execute_requires_executor_confirmation() -> None:
    commands = {item["id"]: item for item in load_catalog()["commands"]}

    assert commands["workflow.execute"]["exposure"] == "agent-confirmation"
    assert commands["workflow.execute"]["confirmation"] == "required"


def test_catalog_commands_match_required_keys_and_closed_enums() -> None:
    cli_root = Path(__file__).resolve().parents[1]
    schema = __import__("json").loads(
        (cli_root / "catalog" / "tool-catalog.schema.json").read_text(encoding="utf-8")
    )
    command_schema = schema["$defs"]["command"]
    required = set(command_schema["required"])
    properties = command_schema["properties"]
    commands = load_catalog()["commands"]
    command_ids = [item["id"] for item in commands]

    assert len(command_ids) == len(set(command_ids))
    for command in commands:
        assert required <= set(command) <= set(properties)
        for field in ("exposure", "status", "transport", "confirmation"):
            assert command[field] in properties[field]["enum"]
        if "input_transport" in command:
            assert command["input_transport"] in properties["input_transport"]["enum"]


def _resolve_json_pointer(document: object, pointer: str) -> object:
    current = document
    for raw_segment in pointer.removeprefix("#/").split("/"):
        segment = unquote(raw_segment).replace("~1", "/").replace("~0", "~")
        assert isinstance(current, dict), f"Pointer segment {segment!r} is not an object"
        assert segment in current, f"Pointer segment {segment!r} does not exist"
        current = current[segment]
    return current


def test_every_command_has_a_resolvable_schema_source() -> None:
    cli_root = Path(__file__).resolve().parents[1]
    repository_root = cli_root.parent
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))

    from app.main import app

    catalog = yaml.safe_load(
        (cli_root / "catalog" / "tool-catalog.yaml").read_text(encoding="utf-8")
    )
    local_contracts = yaml.safe_load(
        (cli_root / "catalog" / "cli-contracts.yaml").read_text(encoding="utf-8")
    )["contracts"]
    openapi = app.openapi()

    for command in catalog["commands"]:
        for field, leaf in (
            ("input_schema_source", "input"),
            ("output_schema_source", "output"),
        ):
            source = command[field]
            if source.startswith("openapi://platform#"):
                resolved = _resolve_json_pointer(
                    openapi,
                    source.removeprefix("openapi://platform"),
                )
                assert isinstance(resolved, dict)
            else:
                prefix = "cli://contracts/"
                assert source.startswith(prefix)
                contract_id, source_leaf = source.removeprefix(prefix).rsplit("/", 1)
                assert source_leaf == leaf
                assert contract_id in local_contracts
                assert leaf in local_contracts[contract_id]


def test_schema_source_fields_are_required_by_catalog_schema() -> None:
    cli_root = Path(__file__).resolve().parents[1]
    schema = __import__("json").loads(
        (cli_root / "catalog" / "tool-catalog.schema.json").read_text(encoding="utf-8")
    )

    required = set(schema["$defs"]["command"]["required"])
    assert {"input_schema_source", "output_schema_source"} <= required
    properties = schema["$defs"]["command"]["properties"]
    assert properties["exposure"]["enum"] == [
        "agent-default",
        "agent-confirmation",
    ]
    assert properties["status"]["enum"] == ["cli-ready", "deferred"]
    assert properties["transport"]["enum"] == ["http", "composite"]
