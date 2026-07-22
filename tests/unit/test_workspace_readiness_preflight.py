# ruff: noqa: E501
# SQL fixture strings below are kept verbatim for readiness preflight coverage.

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

import pytest

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check-workspace-rbac-readiness.py"
ProviderSeed = tuple[str, str, str | None]


class CheckReport(TypedDict):
    ok: bool
    violation_count: int
    sample_ids: list[str]


class ReadinessReport(TypedDict):
    ok: bool
    database_url: str
    checks: dict[str, CheckReport]


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


def _create_sqlite_database(monkeypatch: pytest.MonkeyPatch, database_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    return database_url


def _seed_clean_data(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            INSERT INTO users (id, email, password_hash, name, last_workspace_id)
            VALUES ('user_1', 'alice@example.com', 'hash', 'Alice', NULL);

            INSERT INTO workspaces (id, name, slug, description, owner_user_id)
            VALUES ('ws_1', 'Workspace 1', 'workspace-1', NULL, 'user_1');

            INSERT INTO workspace_members (id, workspace_id, user_id, role)
            VALUES ('member_1', 'ws_1', 'user_1', 'owner');

            INSERT INTO workflows (id, workflow_key, name, description, workspace_id, current_definition_json, latest_version, published_version, created_by_user_id, last_saved_by_user_id)
            VALUES ('wf_1', 'workflow-key-1', 'Workflow 1', NULL, 'ws_1', '{"nodes": [], "connections": []}', 1, NULL, 'user_1', 'user_1');

            INSERT INTO test_sets (id, name, description, workspace_id, document_count)
            VALUES ('ts_1', 'Test Set 1', NULL, 'ws_1', 0);

            INSERT INTO evaluation_runs (id, name, test_set_id, workspace_id, workflow_id, workflow_version, workflow_snapshot_json, client_request_id, status, total_documents, completed_count, failed_count, started_at, completed_at, duration_ms)
            VALUES ('er_1', 'Eval 1', 'ts_1', 'ws_1', 'wf_1', 1, NULL, NULL, 'completed', 1, 1, 0, NULL, NULL, NULL);

            INSERT INTO task_runs (id, status, workflow_id, workflow_name, run_name, source, workspace_id, evaluation_run_id, created_at, completed_at, duration_ms, node_summary_json, result_preview, results_json, error, dag_hash, input_files_json, workflow_json, updated_at)
            VALUES ('tr_1', 'completed', 'wf_1', 'Workflow 1', 'Run 1', 'manual', 'ws_1', 'er_1', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

            UPDATE users SET last_workspace_id = 'ws_1' WHERE id = 'user_1';
            """
        )
        connection.commit()


def _seed_provider(database_path: Path, provider: ProviderSeed) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE model_providers (id TEXT PRIMARY KEY, scope TEXT NOT NULL, workspace_id TEXT)"
        )
        connection.execute(
            "INSERT INTO model_providers (id, scope, workspace_id) VALUES (?, ?, ?)", provider
        )


def _run_script(
    database_url: str,
    provider_database_path: Path,
    *,
    enforced: bool = False,
    mode: str = "pre-migration",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["PROVIDER_DB_PATH"] = str(provider_database_path)
    env["WORKSPACE_RBAC_ENFORCED"] = str(enforced).lower()
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--mode", mode],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_report(result: subprocess.CompletedProcess[str]) -> ReadinessReport:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def test_workspace_readiness_preflight_exits_zero_for_clean_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-clean.sqlite3"
    provider_database_path = tmp_path / "providers.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    result = _run_script(database_url, provider_database_path)

    assert result.returncode == 0, result.stdout + result.stderr
    report = _parse_report(result)
    assert report["ok"] is True
    checks = report["checks"]
    assert checks["resource_workspace_ids_present"]["violation_count"] == 0
    assert checks["resource_workspace_ids_resolve"]["violation_count"] == 0
    assert checks["workspaces_have_owner_membership"]["violation_count"] == 0
    assert checks["workspaces_have_exactly_one_owner"]["violation_count"] == 0
    assert checks["users_last_workspace_membership_valid"]["violation_count"] == 0
    assert checks["provider_legacy_rows"]["violation_count"] == 0
    assert not provider_database_path.exists()


def test_workspace_readiness_preflight_fails_for_null_workspace_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-null.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE workflows SET workspace_id = NULL WHERE id = 'wf_1'")
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3")

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["resource_workspace_ids_present"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["wf_1"]


def test_workspace_readiness_preflight_fails_for_dangling_workspace_fk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-dangling.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("UPDATE workflows SET workspace_id = 'ws_missing' WHERE id = 'wf_1'")
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3")

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["resource_workspace_ids_resolve"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["wf_1"]


def test_workspace_readiness_preflight_fails_for_ownerless_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-ownerless.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM workspace_members WHERE id = 'member_1'")
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3")

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["workspaces_have_owner_membership"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["ws_1"]


def test_workspace_readiness_preflight_fails_for_duplicate_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-duplicate-owner.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO users (id, email, password_hash, name, last_workspace_id)
            VALUES ('user_2', 'bob@example.com', 'hash', 'Bob', NULL);
            INSERT INTO workspace_members (id, workspace_id, user_id, role)
            VALUES ('member_2', 'ws_1', 'user_2', 'owner');
            """
        )
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3")

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["workspaces_have_exactly_one_owner"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["ws_1"]


def test_workspace_readiness_preflight_fails_for_broken_last_workspace_membership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-broken-last-workspace.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO users (id, email, password_hash, name, last_workspace_id)
            VALUES ('user_2', 'bob@example.com', 'hash', 'Bob', 'ws_1')
            """
        )
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3")

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["users_last_workspace_membership_valid"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["user_2"]


def test_workspace_readiness_preflight_reports_provider_legacy_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "workspace-readiness-provider-legacy.sqlite3"
    provider_database_path = tmp_path / "providers.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    _seed_provider(provider_database_path, ("provider_legacy", "legacy_unassigned", None))

    result = _run_script(database_url, provider_database_path, enforced=True)

    assert result.returncode != 0
    report = _parse_report(result)
    check = report["checks"]["provider_legacy_rows"]
    assert check["ok"] is False
    assert check["violation_count"] == 1
    assert check["sample_ids"] == ["provider_legacy"]


def test_workspace_readiness_preflight_accepts_assigned_workspace_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path, provider_database_path = (
        tmp_path / "workspace-readiness-provider-assigned.sqlite3",
        tmp_path / "providers.sqlite3",
    )
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    _seed_provider(provider_database_path, ("provider_assigned", "workspace", "ws_1"))

    result = _run_script(database_url, provider_database_path, enforced=True)

    assert result.returncode == 0, result.stdout + result.stderr
    checks = _parse_report(result)["checks"]
    assert checks["provider_scopes_valid"]["violation_count"] == 0
    assert checks["provider_workspace_ids_resolve"]["violation_count"] == 0


def test_workspace_readiness_preflight_rejects_invalid_provider_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path, provider_database_path = (
        tmp_path / "workspace-readiness-provider-invalid-scope.sqlite3",
        tmp_path / "providers.sqlite3",
    )
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    _seed_provider(provider_database_path, ("provider_invalid", "shared", None))

    result = _run_script(database_url, provider_database_path, enforced=True)

    assert result.returncode != 0
    check = _parse_report(result)["checks"]["provider_scopes_valid"]
    assert (check["violation_count"], check["sample_ids"]) == (1, ["provider_invalid"])


def test_workspace_readiness_preflight_rejects_missing_provider_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path, provider_database_path = (
        tmp_path / "workspace-readiness-provider-missing-workspace.sqlite3",
        tmp_path / "providers.sqlite3",
    )
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    _seed_provider(provider_database_path, ("provider_dangling", "workspace", "ws_missing"))

    result = _run_script(database_url, provider_database_path, enforced=True)

    assert result.returncode != 0
    check = _parse_report(result)["checks"]["provider_workspace_ids_resolve"]
    assert (check["violation_count"], check["sample_ids"]) == (1, ["provider_dangling"])


@pytest.mark.parametrize(
    ("statement", "check_name"),
    [
        ("UPDATE workspaces SET owner_user_id = 'user_missing'", "workspace_owner_user_ids_match"),
        ("UPDATE workspace_members SET role = 'superuser'", "workspace_roles_valid"),
        (
            "UPDATE evaluation_runs SET workspace_id = 'ws_missing'",
            "evaluation_relationships_valid",
        ),
        ("UPDATE task_runs SET workspace_id = 'ws_missing'", "task_relationships_valid"),
    ],
)
def test_full_readiness_rejects_relationship_invariants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    statement: str,
    check_name: str,
) -> None:
    database_path = tmp_path / f"{check_name}.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(statement)
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3", mode="full")

    assert result.returncode != 0
    assert _parse_report(result)["checks"][check_name]["violation_count"] == 1


def test_full_readiness_recovers_nonempty_deleting_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "deleting.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE workspaces SET status = 'deleting'")
        connection.commit()

    result = _run_script(database_url, tmp_path / "providers.sqlite3", mode="full")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _parse_report(result)["checks"]["deleting_workspaces_recovered"]["violation_count"] == 0
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT status FROM workspaces").fetchone()[0] == "active"


def test_readiness_redacts_database_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "redacted.sqlite3"
    database_url = _create_sqlite_database(monkeypatch, database_path)
    _seed_clean_data(database_path)

    result = _run_script(database_url, tmp_path / "providers.sqlite3", mode="full")

    assert "password" not in _parse_report(result)["database_url"]
