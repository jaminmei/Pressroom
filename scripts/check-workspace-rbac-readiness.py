#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
# ─── How to run ───
# uv run python scripts/check-workspace-rbac-readiness.py --mode full

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
from typing import Final, TypedDict

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import make_url, text  # noqa: E402

from app.db.session import _get_engine  # noqa: E402
from app.db.url import get_database_url  # noqa: E402
from app.providers.db import get_db_path  # noqa: E402

RESOURCE_TABLES: Final = (
    "workflows",
    "test_sets",
    "evaluation_runs",
    "task_runs",
    "api_keys",
    "api_invocations",
)
VALID_ROLES: Final = ("owner", "admin", "editor", "runner", "viewer")
SAMPLE_LIMIT: Final = 20


class CheckReport(TypedDict):
    ok: bool
    violation_count: int
    sample_ids: list[str]


class ReadinessReport(TypedDict):
    ok: bool
    database_url: str
    checks: dict[str, CheckReport]


def _check(query: str) -> CheckReport:
    with _get_engine().connect() as connection:
        ids = [
            str(value)
            for value in connection.execute(text(query), {"limit": SAMPLE_LIMIT}).scalars()
        ]
    return {"ok": not ids, "violation_count": len(ids), "sample_ids": ids[:SAMPLE_LIMIT]}


def _union_check(selects: list[str]) -> CheckReport:
    return _check(
        f"SELECT id FROM ({' UNION ALL '.join(selects)}) violations ORDER BY id LIMIT :limit"
    )


def _clean() -> CheckReport:
    return {"ok": True, "violation_count": 0, "sample_ids": []}


def _provider_rows() -> tuple[list[str], list[str], list[str], list[str]]:
    path = get_db_path()
    if not path.is_file():
        return [], [], [], []
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_providers'"
            ).fetchone()
            is None
        ):
            return [], [], [], []
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(model_providers)")}
        if not {"scope", "workspace_id"}.issubset(columns):
            ids = [str(row[0]) for row in connection.execute("SELECT id FROM model_providers")]
            return ids, ids, [], []
        rows = connection.execute(
            "SELECT id, scope, workspace_id, "
            + ("is_default" if "is_default" in columns else "0")
            + ", "
            + ("engine_category" if "engine_category" in columns else "'unknown'")
            + " FROM model_providers ORDER BY id"
        ).fetchall()
    legacy = [str(row[0]) for row in rows if row[1] == "legacy_unassigned"]
    invalid_scope = [
        str(row[0])
        for row in rows
        if row[1] not in {"system", "workspace", "legacy_unassigned"}
        or (row[1] == "workspace") != bool(row[2])
    ]
    workspace_rows = [(str(row[0]), str(row[2])) for row in rows if row[1] == "workspace"]
    invalid_defaults = [str(row[0]) for row in rows if row[1] == "legacy_unassigned" and row[3]]
    default_keys: set[tuple[str, str, str]] = set()
    for provider_id, scope, workspace_id, is_default, category in rows:
        key = (str(scope), str(workspace_id or ""), str(category))
        if is_default and key in default_keys:
            invalid_defaults.append(str(provider_id))
        if is_default:
            default_keys.add(key)
    with _get_engine().connect() as connection:
        missing = [
            provider_id
            for provider_id, workspace_id in workspace_rows
            if connection.execute(
                text("SELECT 1 FROM workspaces WHERE id=:id"), {"id": workspace_id}
            ).first()
            is None
        ]
    return legacy, invalid_scope, missing, invalid_defaults


def _ids_report(ids: list[str], *, enforced: bool = True) -> CheckReport:
    visible = ids if enforced else []
    return {
        "ok": not visible,
        "violation_count": len(visible),
        "sample_ids": visible[:SAMPLE_LIMIT],
    }


def _provider_count(workspace_id: str) -> int:
    path = get_db_path()
    if not path.is_file():
        return 0
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM model_providers WHERE scope='workspace' AND workspace_id=?",
                (workspace_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
    return int(row[0]) if row is not None else 0


def _recover_deleting_workspaces() -> CheckReport:
    with _get_engine().begin() as connection:
        deleting = [
            str(value)
            for value in connection.execute(
                text("SELECT id FROM workspaces WHERE status='deleting'")
            ).scalars()
        ]
        unresolved: list[str] = []
        for workspace_id in deleting:
            resource_count = sum(
                int(
                    connection.execute(
                        text(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=:id"),
                        {"id": workspace_id},
                    ).scalar_one()
                )
                for table in RESOURCE_TABLES
            )
            member_count = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM workspace_members "
                        "WHERE workspace_id=:id AND role!='owner'"
                    ),
                    {"id": workspace_id},
                ).scalar_one()
            )
            if resource_count + member_count + _provider_count(workspace_id):
                connection.execute(
                    text("UPDATE workspaces SET status='active' WHERE id=:id"),
                    {"id": workspace_id},
                )
            else:
                unresolved.append(workspace_id)
    return _ids_report(unresolved)


def build_report(mode: str = "pre-migration") -> ReadinessReport:
    present = _union_check(
        [f"SELECT id FROM {table} WHERE workspace_id IS NULL" for table in RESOURCE_TABLES]
    )
    resolves = _union_check(
        [
            f"SELECT resource.id FROM {table} resource LEFT JOIN workspaces w "
            "ON w.id=resource.workspace_id WHERE resource.workspace_id IS NOT NULL AND w.id IS NULL"
            for table in RESOURCE_TABLES
        ]
    )
    roles = ",".join(f"'{role}'" for role in VALID_ROLES)
    checks: dict[str, CheckReport] = {
        "resource_workspace_ids_present": present,
        "resource_workspace_ids_resolve": resolves,
        "workspaces_have_owner_membership": _check(
            "SELECT w.id FROM workspaces w LEFT JOIN workspace_members m ON m.workspace_id=w.id "
            "AND m.role='owner' WHERE m.id IS NULL ORDER BY w.id LIMIT :limit"
        ),
        "workspaces_have_exactly_one_owner": _check(
            "SELECT w.id FROM workspaces w LEFT JOIN workspace_members m ON m.workspace_id=w.id "
            "AND m.role='owner' GROUP BY w.id HAVING COUNT(m.id)!=1 ORDER BY w.id LIMIT :limit"
        ),
        "workspace_owner_user_ids_match": _check(
            "SELECT w.id FROM workspaces w LEFT JOIN workspace_members m ON m.workspace_id=w.id "
            "AND m.role='owner' AND m.user_id=w.owner_user_id WHERE m.id IS NULL "
            "ORDER BY w.id LIMIT :limit"
        ),
        "workspace_roles_valid": _check(
            f"SELECT id FROM workspace_members WHERE role NOT IN ({roles}) ORDER BY id LIMIT :limit"
        ),
        "users_last_workspace_membership_valid": _check(
            "SELECT u.id FROM users u LEFT JOIN workspace_members m "
            "ON m.workspace_id=u.last_workspace_id "
            "AND m.user_id=u.id WHERE u.last_workspace_id IS NOT NULL AND m.id IS NULL "
            "ORDER BY u.id LIMIT :limit"
        ),
    }
    legacy, scopes, provider_workspaces, defaults = _provider_rows()
    provider_enforced = (
        mode == "full" or os.environ.get("WORKSPACE_RBAC_ENFORCED", "").lower() == "true"
    )
    checks.update(
        {
            "provider_legacy_rows": _ids_report(legacy, enforced=provider_enforced),
            "provider_scopes_valid": _ids_report(scopes, enforced=provider_enforced),
            "provider_workspace_ids_resolve": _ids_report(
                provider_workspaces, enforced=provider_enforced
            ),
            "provider_defaults_valid": _ids_report(defaults, enforced=provider_enforced),
        }
    )
    if mode == "full":
        checks.update(
            {
                "evaluation_relationships_valid": _check(
                    "SELECT e.id FROM evaluation_runs e LEFT JOIN workflows w "
                    "ON w.id=e.workflow_id LEFT JOIN test_sets t ON t.id=e.test_set_id "
                    "WHERE w.id IS NULL OR t.id IS NULL "
                    "OR w.workspace_id!=e.workspace_id OR t.workspace_id!=e.workspace_id "
                    "ORDER BY e.id LIMIT :limit"
                ),
                "task_relationships_valid": _check(
                    "SELECT r.id FROM task_runs r LEFT JOIN workflows w ON w.id=r.workflow_id "
                    "LEFT JOIN evaluation_runs e ON e.id=r.evaluation_run_id "
                    "WHERE (r.workflow_id IS NOT NULL AND "
                    "(w.id IS NULL OR w.workspace_id!=r.workspace_id)) "
                    "OR (r.evaluation_run_id IS NOT NULL AND "
                    "(e.id IS NULL OR e.workspace_id!=r.workspace_id)) "
                    "ORDER BY r.id LIMIT :limit"
                ),
                "api_key_relationships_valid": _check(
                    "SELECT k.id FROM api_keys k LEFT JOIN workflows w ON w.id=k.workflow_id "
                    "WHERE w.id IS NULL ORDER BY k.id LIMIT :limit"
                ),
                "api_invocation_relationships_valid": _check(
                    "SELECT i.id FROM api_invocations i LEFT JOIN workflows w "
                    "ON w.id=i.workflow_id LEFT JOIN api_keys k ON k.id=i.api_key_id "
                    "LEFT JOIN task_runs r ON r.id=i.workflow_run_id WHERE w.id IS NULL "
                    "OR (i.api_key_id IS NOT NULL AND "
                    "(k.id IS NULL OR k.workflow_id!=i.workflow_id)) "
                    "OR (i.workflow_run_id IS NOT NULL AND "
                    "(r.id IS NULL OR r.workflow_id!=i.workflow_id)) "
                    "ORDER BY i.id LIMIT :limit"
                ),
                "deleting_workspaces_recovered": _recover_deleting_workspaces(),
            }
        )
    database_url = make_url(get_database_url()).render_as_string(hide_password=True)
    return {
        "ok": all(check["ok"] for check in checks.values()),
        "database_url": database_url,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("pre-migration", "full"), default="pre-migration")
    args = parser.parse_args()
    report = build_report(args.mode)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
