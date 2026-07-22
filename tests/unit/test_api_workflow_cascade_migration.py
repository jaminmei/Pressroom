from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.db.api_invocation import ApiInvocation
from app.models.db.api_key import ApiKey
from app.models.workflow import WorkflowDefinition
from app.services.database_workflow_store import DatabaseWorkflowStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASCADE_REVISION = "20260716_0015"
CASCADE_PARENT_REVISION = "20260715_0014"


def _run_alembic(database_url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _foreign_key_cascades(database_path: Path, table_name: str) -> bool:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    return any(
        row[2] == "workflows" and row[3] == "workflow_id" and row[6] == "CASCADE" for row in rows
    )


def test_api_workflow_cascade_migration_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "api-cascade.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _run_alembic(database_url, "upgrade", CASCADE_PARENT_REVISION)

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            INSERT INTO users (
                id, email, password_hash, name, created_at, updated_at
            ) VALUES (
                'usr_keep', 'keep@example.com', 'hash_keep', 'Keep User',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            INSERT INTO workspaces (
                id, name, slug, owner_user_id, status, created_at, updated_at
            ) VALUES (
                'ws_keep', 'Keep Workspace', 'keep-workspace', 'usr_keep', 'active',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            INSERT INTO workspace_members (
                id, workspace_id, user_id, role, created_at
            ) VALUES (
                'wsm_keep', 'ws_keep', 'usr_keep', 'owner', CURRENT_TIMESTAMP
            );
            INSERT INTO workflows (
                id, workflow_key, name, workspace_id, current_definition_json,
                latest_version, created_at, updated_at
            ) VALUES (
                'wf_keep', 'wk_keep', 'Keep', 'ws_keep', '{"nodes":[],"connections":[]}',
                1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            INSERT INTO api_keys (
                id, key_hash, key_prefix, workflow_id, workspace_id, is_active
            ) VALUES
                ('key_keep', 'hash_keep', 'keep', 'wf_keep', 'ws_keep', 1),
                ('key_orphan', 'hash_orphan', 'orphan', 'wf_missing', 'ws_keep', 1);
            INSERT INTO api_invocations (
                id, workflow_id, workspace_id, endpoint_kind, workflow_status,
                storage_bytes, created_at, updated_at
            ) VALUES
                ('inv_keep', 'wf_keep', 'ws_keep', 'json', 'completed', 0,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('inv_orphan', 'wf_missing', 'ws_keep', 'json', 'completed', 0,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """
        )

    _run_alembic(database_url, "upgrade", CASCADE_REVISION)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id FROM api_keys ORDER BY id").fetchall() == [
            ("key_keep",)
        ]
        assert connection.execute("SELECT id FROM api_invocations ORDER BY id").fetchall() == [
            ("inv_keep",)
        ]

    assert _foreign_key_cascades(database_path, "api_keys")
    assert _foreign_key_cascades(database_path, "api_invocations")

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM workflows WHERE id = 'wf_keep'")
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM api_keys").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM api_invocations").fetchone() == (0,)

    _run_alembic(database_url, "downgrade", CASCADE_PARENT_REVISION)
    assert not _foreign_key_cascades(database_path, "api_keys")
    assert not _foreign_key_cascades(database_path, "api_invocations")

    _run_alembic(database_url, "upgrade", "head")
    assert _foreign_key_cascades(database_path, "api_keys")
    assert _foreign_key_cascades(database_path, "api_invocations")


def test_workflow_store_delete_removes_only_its_api_credentials_and_usage(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'store-delete.sqlite3'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = DatabaseWorkflowStore(session_factory=session_factory)
    first = store.create(
        name="First",
        definition=WorkflowDefinition(nodes=[], connections=[]),
        workspace_id="ws_first",
    )
    second = store.create(
        name="Second",
        definition=WorkflowDefinition(nodes=[], connections=[]),
        workspace_id="ws_second",
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with session_factory() as session:
        for workflow, suffix in ((first, "first"), (second, "second")):
            session.add(
                ApiKey(
                    id=f"key_{suffix}",
                    key_hash=f"hash_{suffix}",
                    key_prefix=suffix,
                    workflow_id=workflow.id,
                    workspace_id=workflow.workspace_id,
                    is_active=True,
                )
            )
            session.add(
                ApiInvocation(
                    id=f"inv_{suffix}",
                    workflow_id=workflow.id,
                    workspace_id=workflow.workspace_id,
                    endpoint_kind="json",
                    workflow_status="completed",
                    storage_bytes=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()

    assert store.delete(first.id, workspace_id="ws_first") is True

    with session_factory() as session:
        assert session.scalars(select(ApiKey.id)).all() == ["key_second"]
        assert session.scalars(select(ApiInvocation.id)).all() == ["inv_second"]
    assert store.get(second.id, workspace_id="ws_second") is not None
    engine.dispose()
