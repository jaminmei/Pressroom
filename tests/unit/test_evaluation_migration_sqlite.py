from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_evaluation_migration_upgrades_on_sqlite() -> None:
    python_bin = sys.executable
    command = (
        "export AUTH_SESSION_SECRET=test-auth-session-secret "
        "DATABASE_URL=sqlite+pysqlite:////tmp/evaluation-backend-test.sqlite3; "
        "rm -f /tmp/evaluation-backend-test.sqlite3; "
        f"{python_bin} -m alembic upgrade 20260319_0003"
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_evaluation_queue_migration_round_trips_on_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "evaluation-queue-roundtrip.sqlite3"
    env = {
        **os.environ,
        "AUTH_SESSION_SECRET": "test-auth-session-secret",
        "DATABASE_URL": f"sqlite+pysqlite:///{database_path}",
    }
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260717_0016"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260716_0015"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert downgrade.returncode == 0, downgrade.stderr


def test_evaluation_queue_migration_reports_duplicate_preflight(tmp_path: Path) -> None:
    database_path = tmp_path / "evaluation-queue-duplicates.sqlite3"
    env = {
        **os.environ,
        "AUTH_SESSION_SECRET": "test-auth-session-secret",
        "DATABASE_URL": f"sqlite+pysqlite:///{database_path}",
    }
    setup = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260716_0015"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    seed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from sqlalchemy import create_engine, text; "
                "import os; "
                "engine=create_engine(os.environ['DATABASE_URL']); "
                "connection=engine.connect(); "
                "transaction=connection.begin(); "
                'connection.execute(text("INSERT INTO test_sets '
                "(id,name,document_count) VALUES ('ts_dup','Duplicate',0)\")); "
                'connection.execute(text("INSERT INTO evaluation_runs '
                "(id,test_set_id,workflow_id,status,total_documents,completed_count,failed_count) "
                "VALUES ('run_a','ts_dup','wf','pending',0,0,0)\")); "
                'connection.execute(text("INSERT INTO evaluation_runs '
                "(id,test_set_id,workflow_id,status,total_documents,completed_count,failed_count) "
                "VALUES ('run_b','ts_dup','wf','running',0,0,0)\")); "
                "transaction.commit(); connection.close()"
            ),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert seed.returncode == 0, seed.stderr

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260717_0016"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert upgrade.returncode != 0
    assert "preflight failed" in (upgrade.stderr + upgrade.stdout)
