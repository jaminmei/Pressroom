#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2"]
# ///
# ─── How to run ───
# uv run python scripts/assign-legacy-providers.py --report

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from typing import Final, Literal, TypeAlias, assert_never

from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

PROJECT_ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.providers.db import get_db_path  # noqa: E402

SHA256_LENGTH: Final = 64
JsonValue: TypeAlias = str | int | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
REPORT_FIELDS: Final = (
    "id",
    "name",
    "engine_category",
    "is_default",
    "scope",
    "workspace_id",
)


class AssignmentError(Exception):
    pass


class MappingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    scope: Literal["system", "workspace"]
    workspace_id: str | None = None
    expected_category: str
    expected_is_default: bool

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value not in {"system", "workspace"}:
            raise PydanticCustomError("invalid_scope", "invalid scope")
        return value

    @model_validator(mode="after")
    def validate_workspace(self) -> MappingEntry:
        match self.scope:
            case "workspace":
                if not self.workspace_id:
                    raise PydanticCustomError(
                        "workspace_required", "workspace scope requires workspace_id"
                    )
            case "system":
                if self.workspace_id is not None:
                    raise PydanticCustomError(
                        "workspace_forbidden", "system scope cannot have workspace_id"
                    )
            case unreachable:
                assert_never(unreachable)
        return self


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_sha256: str
    mapping_sha256: str
    approver: str
    approval_utc: str
    approved_ids: list[str]

    @field_validator("report_sha256", "mapping_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != SHA256_LENGTH or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise PydanticCustomError("invalid_sha256", "must be a lowercase SHA-256")
        return value

    @field_validator("approver", "approval_utc")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("empty_text", "must not be empty")
        return value


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_bytes(value: dict[str, JsonValue]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def build_report() -> dict[str, JsonValue]:
    database_path = get_db_path().resolve()
    if not database_path.is_file():
        return {
            "database": {"path": str(database_path), "sha256": None},
            "schema_version": 0,
            "count": 0,
            "providers": [],
        }

    database_sha256 = sha256_bytes(database_path.read_bytes())
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(model_providers)")}
        scope_select = "scope" if "scope" in columns else "'legacy_unassigned'"
        workspace_select = "workspace_id" if "workspace_id" in columns else "NULL"
        where_clause = "WHERE scope = 'legacy_unassigned'" if "scope" in columns else ""
        rows = connection.execute(
            f"""
            SELECT id, name, engine_category, is_default, {scope_select}, {workspace_select}
              FROM model_providers {where_clause} ORDER BY id
            """  # noqa: S608
        ).fetchall()
    providers: list[dict[str, JsonValue]] = []
    for row in rows:
        public_row: dict[str, JsonValue] = dict(zip(REPORT_FIELDS, row, strict=True))
        public_row["is_default"] = bool(public_row["is_default"])
        public_row["row_sha256"] = sha256_bytes(
            json.dumps(public_row, sort_keys=True, separators=(",", ":")).encode()
        )
        providers.append(public_row)
    return {
        "database": {"path": str(database_path), "sha256": database_sha256},
        "schema_version": schema_version,
        "count": len(providers),
        "providers": providers,
    }


def load_inputs(
    mapping_path: pathlib.Path, approval_path: pathlib.Path
) -> tuple[list[MappingEntry], Approval]:
    try:
        mapping_content = mapping_path.read_bytes()
        approval_content = approval_path.read_bytes()
        mappings = TypeAdapter(list[MappingEntry]).validate_json(mapping_content)
        approval = Approval.model_validate_json(approval_content)
    except (OSError, ValidationError) as error:
        raise AssignmentError(str(error)) from error
    mapping_ids = [item.provider_id for item in mappings]
    if len(mapping_ids) != len(set(mapping_ids)):
        raise AssignmentError("mapping contains duplicate provider IDs")
    if sha256_bytes(mapping_content) != approval.mapping_sha256:
        raise AssignmentError("mapping SHA-256 does not match approval")
    if set(mapping_ids) != set(approval.approved_ids) or len(approval.approved_ids) != len(
        set(approval.approved_ids)
    ):
        raise AssignmentError("approved ID set differs from mapping ID set")
    return mappings, approval


def validate_live_state(
    connection: sqlite3.Connection,
    mappings: list[MappingEntry],
    expected_report_sha256: str,
    approval: Approval,
) -> Literal["pending", "already_applied"]:
    if expected_report_sha256 != approval.report_sha256:
        raise AssignmentError("expected report SHA-256 does not match approval")
    rows = connection.execute(
        "SELECT id, engine_category, is_default, scope, workspace_id FROM model_providers"
    ).fetchall()
    by_id = {str(row[0]): row for row in rows}
    mapping_ids = {item.provider_id for item in mappings}
    unknown_ids = mapping_ids - by_id.keys()
    if unknown_ids:
        raise AssignmentError(f"unknown provider IDs: {sorted(unknown_ids)}")
    for item in mappings:
        row = by_id[item.provider_id]
        if row[1] != item.expected_category:
            raise AssignmentError(f"provider {item.provider_id} category changed")
        if bool(row[2]) is not item.expected_is_default:
            raise AssignmentError(f"provider {item.provider_id} default status changed")
    legacy_ids = {str(row[0]) for row in rows if row[3] == "legacy_unassigned"}
    already_applied = not legacy_ids and all(
        by_id[item.provider_id][3:] == (item.scope, item.workspace_id) for item in mappings
    )
    if already_applied:
        return "already_applied"
    if legacy_ids != mapping_ids:
        raise AssignmentError("live legacy ID set differs from mapping ID set")
    if sha256_bytes(json_bytes(build_report())) != expected_report_sha256:
        raise AssignmentError("live report SHA-256 differs from expected report SHA-256")
    return "pending"


def execute_assignment(
    mappings: list[MappingEntry],
    approval: Approval,
    expected_report_sha256: str,
    *,
    apply: bool,
) -> dict[str, JsonValue]:
    database_path = get_db_path().resolve()
    if not database_path.is_file():
        raise AssignmentError(f"Provider database does not exist: {database_path}")
    mode = "rw" if apply else "ro"
    with sqlite3.connect(f"file:{database_path}?mode={mode}", uri=True) as connection:
        state = validate_live_state(connection, mappings, expected_report_sha256, approval)
        if apply and state == "pending":
            for item in mappings:
                cursor = connection.execute(
                    """
                    UPDATE model_providers SET scope = ?, workspace_id = ?
                     WHERE id = ? AND scope = 'legacy_unassigned'
                    """,
                    (item.scope, item.workspace_id, item.provider_id),
                )
                if cursor.rowcount != 1:
                    raise AssignmentError(f"provider {item.provider_id} changed during apply")
    status = (
        "already_applied" if state == "already_applied" else "applied" if apply else "validated"
    )
    return {
        "status": status,
        "count": len(mappings),
        "provider_ids": sorted(item.provider_id for item in mappings),
    }


def write_output(result: dict[str, JsonValue], output: pathlib.Path | None) -> None:
    content = json_bytes(result)
    if output is None:
        sys.stdout.buffer.write(content)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--mapping", type=pathlib.Path)
    parser.add_argument("--approval", type=pathlib.Path)
    parser.add_argument("--expected-report-sha256")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    arguments = parser.parse_args()
    assignment_values = (arguments.mapping, arguments.approval, arguments.expected_report_sha256)
    assignment_requested = (
        any(value is not None for value in assignment_values)
        or arguments.dry_run
        or arguments.apply
    )
    if arguments.report and assignment_requested:
        parser.error("--report cannot be combined with assignment options")
    if not assignment_requested:
        write_output(build_report(), arguments.output)
        return 0
    if not all(value is not None for value in assignment_values) or not (
        arguments.dry_run or arguments.apply
    ):
        parser.error(
            "assignment requires --mapping, --approval, "
            "--expected-report-sha256, and one of --dry-run/--apply"
        )
    try:
        mappings, approval = load_inputs(arguments.mapping, arguments.approval)
        result = execute_assignment(
            mappings,
            approval,
            arguments.expected_report_sha256,
            apply=arguments.apply,
        )
    except (AssignmentError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    write_output(result, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
