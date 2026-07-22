# ruff: noqa: E501
# SQL fixture strings below are kept verbatim so migration assertions match
# the legacy database shape being exercised.

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, create_engine

from app.db.base import Base
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_REVISION = "20260706_0011"
WORKSPACE_REVISION = "20260708_0012"
WORKSPACE_RESOURCE_TABLES = ("workflows", "test_sets", "evaluation_runs", "task_runs")


def _run_alembic(database_url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_legacy_data(database_path: Path) -> str:
    older_user_id = "user_older"
    newer_user_id = "user_newer"
    created_at_older = "2026-07-07 09:00:00"
    created_at_newer = "2026-07-07 10:00:00"
    definition_json = '{"nodes":[],"connections":[]}'

    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            f"""
            PRAGMA foreign_keys = ON;
            INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES
                ('{older_user_id}', 'older@example.com', 'hash-older', 'Older User', '{created_at_older}', '{created_at_older}'),
                ('{newer_user_id}', 'newer@example.com', 'hash-newer', 'Newer User', '{created_at_newer}', '{created_at_newer}');
            INSERT INTO workflows (
                id, workflow_key, name, description, current_definition_json, latest_version,
                published_version, created_by_user_id, last_saved_by_user_id, created_at, updated_at
            ) VALUES (
                'wf_legacy', 'wf_legacy_key', 'Legacy Workflow', 'Legacy workflow for migration test',
                '{definition_json}', 1, 1, '{older_user_id}', '{newer_user_id}', '{created_at_newer}', '{created_at_newer}'
            );
            INSERT INTO test_sets (id, name, description, document_count, created_at, updated_at) VALUES
                ('ts_legacy', 'Legacy Test Set', 'Legacy test set for migration test', 0, '{created_at_newer}', '{created_at_newer}');
            INSERT INTO evaluation_runs (
                id, name, test_set_id, workflow_id, workflow_version, workflow_snapshot_json, status,
                total_documents, completed_count, failed_count, started_at, completed_at, duration_ms, created_at
            ) VALUES (
                'er_legacy', 'Legacy Evaluation Run', 'ts_legacy', 'wf_legacy', 1, '{definition_json}',
                'completed', 1, 1, 0, '{created_at_newer}', '{created_at_newer}', 100, '{created_at_newer}'
            );
            INSERT INTO task_runs (
                id, status, workflow_id, workflow_name, run_name, source, evaluation_run_id, created_at,
                completed_at, duration_ms, node_summary_json, result_preview, results_json, error, dag_hash,
                input_files_json, workflow_json, updated_at
            ) VALUES (
                'tr_legacy', 'completed', 'wf_legacy', 'Legacy Workflow', 'Legacy Task Run', 'manual',
                'er_legacy', '{created_at_newer}', '{created_at_newer}', 100, '{{}}', 'legacy result', '{{}}',
                NULL, 'dag-legacy', '[]', '{definition_json}', '{created_at_newer}'
            );
            """
        )

    return older_user_id


def _sqlite_rows(
    database_path: Path, query: str, params: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(query, params).fetchall()


def _sqlite_row(
    database_path: Path, query: str, params: tuple[object, ...] = ()
) -> sqlite3.Row | None:
    rows = _sqlite_rows(database_path, query, params)
    return rows[0] if rows else None


def _table_columns(database_path: Path, table_name: str) -> set[str]:
    rows = _sqlite_rows(database_path, f"PRAGMA table_info({table_name})")
    return {str(row["name"]) for row in rows}


def _table_exists(database_path: Path, table_name: str) -> bool:
    row = _sqlite_row(
        database_path,
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return row is not None


def _require_row(row: sqlite3.Row | None) -> sqlite3.Row:
    assert row is not None
    return row


@pytest.fixture
def _migration_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[str, None, None]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration_test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    yield database_url


def test_workspace_migration_round_trip(_migration_database_url: str) -> None:
    database_url = _migration_database_url
    database_path = Path(database_url.removeprefix("sqlite+pysqlite:///"))
    engine = create_engine(database_url)
    workspace_table = cast(Table, Workspace.__table__)
    workspace_member_table = cast(Table, WorkspaceMember.__table__)

    try:
        _run_alembic(database_url, "upgrade", BASE_REVISION)

        Base.metadata.remove(workspace_table)
        Base.metadata.remove(workspace_member_table)
        Base.metadata.create_all(bind=engine)

        older_user_id = _seed_legacy_data(database_path)

        _run_alembic(database_url, "upgrade", WORKSPACE_REVISION)

        assert (
            _require_row(
                _sqlite_row(
                    database_path,
                    "SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1",
                ),
            )["id"]
            == older_user_id
        )

        for table_name in WORKSPACE_RESOURCE_TABLES:
            rows = _sqlite_rows(
                database_path,
                f"SELECT id, workspace_id FROM {table_name} ORDER BY id",
            )
            assert rows
            assert all(row["workspace_id"] == "ws_legacy" for row in rows)

        workspace = _sqlite_row(
            database_path,
            "SELECT id, owner_user_id FROM workspaces WHERE id = ?",
            ("ws_legacy",),
        )
        assert workspace is not None
        assert workspace["owner_user_id"] == older_user_id

        membership = _sqlite_row(
            database_path,
            """
            SELECT role
            FROM workspace_members
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            ("ws_legacy", older_user_id),
        )
        assert membership is not None
        assert membership["role"] == "owner"

        _run_alembic(database_url, "downgrade", BASE_REVISION)

        assert not _table_exists(database_path, "workspaces")
        assert not _table_exists(database_path, "workspace_members")
        assert "workspace_id" not in _table_columns(database_path, "workflows")

        _run_alembic(database_url, "upgrade", "head")

        for table_name in WORKSPACE_RESOURCE_TABLES:
            rows = _sqlite_rows(
                database_path,
                f"SELECT id, workspace_id FROM {table_name} ORDER BY id",
            )
            assert rows
            assert all(row["workspace_id"] == "ws_legacy" for row in rows)

        assert (
            _require_row(
                _sqlite_row(
                    database_path,
                    "SELECT id, owner_user_id FROM workspaces WHERE id = ?",
                    ("ws_legacy",),
                ),
            )["owner_user_id"]
            == older_user_id
        )

        assert (
            _require_row(
                _sqlite_row(
                    database_path,
                    """
                SELECT role
                FROM workspace_members
                WHERE workspace_id = ? AND user_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                    ("ws_legacy", older_user_id),
                ),
            )["role"]
            == "owner"
        )
    finally:
        Base.metadata.remove(workspace_table)
        Base.metadata.remove(workspace_member_table)
        workspace_table.to_metadata(Base.metadata)
        workspace_member_table.to_metadata(Base.metadata)
        engine.dispose()
