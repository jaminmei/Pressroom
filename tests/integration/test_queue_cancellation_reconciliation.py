from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.worker_tasks as worker_tasks
from app.api import tasks as task_api
from app.models.auth import AuthSessionInfo, AuthUser
from app.services.dag_scheduler import DAGRunResult
from app.services.workspace_access import ResolvedContext
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole


def test_late_worker_completion_does_not_replace_cancelled_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'queue_cancel.sqlite'}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("updated_at", DateTime(timezone=False)),
    )
    metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_tasks, "_column_cache", {})

    with session_factory() as session:
        session.execute(
            task_runs.insert().values(
                id="task_cancelled",
                status="cancelled",
                updated_at=datetime.now(timezone.utc),
            )
        )
        worker_tasks._upsert_task_run(
            session,
            task_run_id="task_cancelled",
            status="completed",
            updated_at=datetime.now(timezone.utc),
        )
        session.commit()

    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "task_cancelled")
            ).scalar_one()
            == "cancelled"
        )


@pytest.mark.asyncio
async def test_queue_cancellation_persists_before_celery_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _Repository:
        async def upsert_snapshot(self, **_kwargs: object) -> None:
            events.append("persist")

    class _Control:
        def revoke(self, task_id: str, terminate: bool) -> None:
            assert task_id == "task_queue_cancel"
            assert terminate is False
            events.append("revoke")

    running_task = SimpleNamespace(workspace_id="ws_queue", cancel_requested=False)
    request = Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(
                state=SimpleNamespace(running_tasks={"task_queue_cancel": running_task})
            ),
        }
    )
    monkeypatch.setattr(task_api, "get_task_run_repository", lambda: _Repository())
    monkeypatch.setattr("app.api.tasks.FeatureFlags.is_queue_mode", lambda: True)
    monkeypatch.setattr("app.worker.celery_app.control", _Control())

    response = await task_api.cancel_task(
        request,
        "task_queue_cancel",
        ResolvedContext(
            user=AuthUser(id="user_queue", email="queue@example.com"),
            session=AuthSessionInfo(
                id="session_queue",
                user_id="user_queue",
                expires_at=datetime.now(timezone.utc),
            ),
            workspace_id="ws_queue",
            role=WorkspaceRole.OWNER,
            capabilities=frozenset(CAPABILITIES[WorkspaceRole.OWNER]),
        ),
    )

    assert response.status_code == 200
    assert running_task.cancel_requested is True
    assert events == ["persist", "revoke"]


def test_full_queue_dag_preserves_cancelled_status_after_worker_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'queue_cancel_full.sqlite'}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("workspace_id", String),
        Column("updated_at", DateTime(timezone=False)),
    )
    metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: Fernet.generate_key())

    with session_factory() as session:
        session.execute(
            task_runs.insert().values(
                id="task_cancelled_dag",
                status="cancelled",
                workspace_id="ws_queue",
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    def _fake_execute_workflow_sync(**kwargs):
        cancel_check = kwargs["cancel_check"]
        assert cancel_check is not None
        assert cancel_check() is True
        return DAGRunResult(completed={}, failed={"adaptor_1": "cancelled"}, skipped=set())

    monkeypatch.setattr(worker_tasks, "execute_workflow_sync", _fake_execute_workflow_sync)

    result = worker_tasks.execute_workflow_task_sync(
        "task_cancelled_dag",
        {
            "nodes": [
                {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
                {
                    "id": "adaptor_1",
                    "type": "processor/adaptor",
                    "config": {"code": "def main(inputs):\n    return {'text': 'ok'}"},
                },
            ],
            "connections": [{"source": "input_1", "target": "adaptor_1", "target_port": "input"}],
        },
        {
            "input_1": {
                "file_path": str(tmp_path / "input.txt"),
                "filename": "input.txt",
                "mime_type": "text/plain",
                "workspace_id": "ws_queue",
            }
        },
        context_data={"workspace_id": "ws_queue"},
    )

    assert result["status"] == "failed"
    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "task_cancelled_dag")
            ).scalar_one()
            == "cancelled"
        )
