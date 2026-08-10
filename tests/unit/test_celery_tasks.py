from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from celery import Celery
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import sessionmaker

import app.worker_tasks as worker_tasks
from app.errors import EngineError, ErrorCode


class _ResponseStub:
    def __init__(self, body: object) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._body


class _SyncClientStub:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[dict[str, object]] = []
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> "_SyncClientStub":
        self.entered += 1
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)
        self.exited += 1
        return None

    def post(self, url: str, json: dict[str, object]) -> _ResponseStub:
        self.calls.append({"url": url, "json": json})
        if self.should_fail:
            raise httpx.HTTPError("engine down")
        return _ResponseStub({"output": {"content": {"children": [{"text": "ok"}]}}})


def _build_test_db(tmp_path: Path) -> tuple[sessionmaker, Table, Table, Table]:
    db_file = tmp_path / "celery_tasks.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()

    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("workflow_id", String),
        Column("workflow_name", String),
        Column("run_name", String),
        Column("source", String),
        Column("evaluation_run_id", String),
        Column("duration_ms", Integer),
        Column("node_summary_json", Text),
        Column("result_preview", Text),
        Column("error", Text),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    node_runs = Table(
        "node_runs",
        metadata,
        Column("node_run_id", String, primary_key=True),
        Column("task_run_id", String),
        Column("node_id", String),
        Column("node_type", String),
        Column("status", String),
        Column("attempt", Integer),
        Column("duration_ms", Integer),
        Column("error", Text),
        Column("started_at", DateTime(timezone=False)),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    task_event_logs = Table(
        "task_event_logs",
        metadata,
        Column("seq", Integer, primary_key=True, autoincrement=True),
        Column("task_run_id", String, nullable=False),
        Column("event_type", String, nullable=False),
        Column("payload", JSON, nullable=True),
        Column("created_at", DateTime(timezone=False)),
    )
    metadata.create_all(engine)

    return (
        sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False),
        task_runs,
        node_runs,
        task_event_logs,
    )


def _workflow_def() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"temperature": 0}},
            {"id": "output_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }


def test_register_worker_tasks_includes_smoke_task() -> None:
    celery_app = Celery("test-docconv")
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True

    worker_tasks.register_worker_tasks(celery_app)

    assert worker_tasks.WORKER_SMOKE_TASK_NAME in celery_app.tasks
    result = celery_app.tasks[worker_tasks.WORKER_SMOKE_TASK_NAME].apply(args=["ping"]).get()
    assert result == {"echo": "ping"}


def test_execute_workflow_task_sync_updates_task_runs_node_runs_and_event_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, node_runs, task_event_logs = _build_test_db(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_engine_url="http://ocr.test",
            vlm_engine_url="http://vlm.test",
            text_engine_url="http://text.test",
            markitdown_engine_url="http://md.test",
        ),
    )

    client = _SyncClientStub(should_fail=False)
    monkeypatch.setattr(worker_tasks.httpx, "Client", lambda timeout: client)

    input_file = tmp_path / "input.txt"
    input_file.write_text("worker input", encoding="utf-8")
    input_data: dict[str, object] = {
        "input_1": {"file_path": str(input_file), "filename": "input.txt"}
    }

    result = worker_tasks.execute_workflow_task_sync(
        "task_worker_success",
        _workflow_def(),
        input_data,
        context_data={
            "workflow_id": "wf_eval_001",
            "workflow_name": "Eval Workflow",
            "run_name": "Eval Run",
            "source": "evaluation",
            "evaluation_run_id": "eval_run_001",
        },
    )

    assert result["status"] == "completed"
    assert len(client.calls) == 1
    assert client.calls[0]["url"] == "http://text.test/process"

    with session_factory() as session:
        task_row = session.execute(
            select(
                task_runs.c.status,
                task_runs.c.node_summary_json,
                task_runs.c.workflow_id,
                task_runs.c.workflow_name,
                task_runs.c.run_name,
                task_runs.c.source,
                task_runs.c.evaluation_run_id,
            ).where(task_runs.c.id == "task_worker_success")
        ).one()
        assert task_row.status == "completed"
        assert json.loads(task_row.node_summary_json) == {"total": 1, "completed": 1, "failed": 0}
        assert task_row.workflow_id == "wf_eval_001"
        assert task_row.workflow_name == "Eval Workflow"
        assert task_row.run_name == "Eval Run"
        assert task_row.source == "evaluation"
        assert task_row.evaluation_run_id == "eval_run_001"

        node_row = session.execute(
            select(node_runs.c.status, node_runs.c.node_id).where(
                node_runs.c.task_run_id == "task_worker_success"
            )
        ).one()
        assert node_row.status == "completed"
        assert node_row.node_id == "engine_1"

        events = (
            session.execute(
                select(task_event_logs.c.event_type).where(
                    task_event_logs.c.task_run_id == "task_worker_success"
                )
            )
            .scalars()
            .all()
        )
        assert events == ["task_running", "node_started", "node_completed", "task_completed"]


def test_execute_workflow_task_sync_marks_failure_when_engine_call_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, node_runs, task_event_logs = _build_test_db(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_engine_url="http://ocr.test",
            vlm_engine_url="http://vlm.test",
            text_engine_url="http://text.test",
            markitdown_engine_url="http://md.test",
        ),
    )

    client = _SyncClientStub(should_fail=True)
    monkeypatch.setattr(worker_tasks.httpx, "Client", lambda timeout: client)

    input_file = tmp_path / "input.txt"
    input_file.write_text("worker input", encoding="utf-8")
    input_data: dict[str, object] = {
        "input_1": {"file_path": str(input_file), "filename": "input.txt"}
    }

    with pytest.raises(EngineError):
        worker_tasks.execute_workflow_task_sync("task_worker_failure", _workflow_def(), input_data)

    with session_factory() as session:
        task_row = session.execute(
            select(task_runs.c.status, task_runs.c.error).where(
                task_runs.c.id == "task_worker_failure"
            )
        ).one()
        assert task_row.status == "failed"
        assert "engine down" in task_row.error

        node_row = session.execute(
            select(node_runs.c.status, node_runs.c.error).where(
                node_runs.c.task_run_id == "task_worker_failure"
            )
        ).one()
        assert node_row.status == "failed"
        assert "engine down" in node_row.error

        events = (
            session.execute(
                select(task_event_logs.c.event_type).where(
                    task_event_logs.c.task_run_id == "task_worker_failure"
                )
            )
            .scalars()
            .all()
        )
        assert events == ["task_running", "node_started", "node_failed", "task_failed"]


def test_call_engine_sync_uses_timeout_from_config_and_closes_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_engine_url="http://ocr.test",
            vlm_engine_url="http://vlm.test",
            text_engine_url="http://text.test",
            markitdown_engine_url="http://md.test",
        ),
    )

    class _TimeoutConfigStub:
        def resolve_timeout_seconds(self, engine_type: str, *, page_count: int = 1) -> int:
            _ = (engine_type, page_count)
            return 42

    monkeypatch.setattr(worker_tasks, "get_engine_timeout_config", lambda: _TimeoutConfigStub())

    timeouts: list[object] = []
    client = _SyncClientStub(should_fail=False)

    def _client_factory(timeout: object) -> _SyncClientStub:
        timeouts.append(timeout)
        return client

    monkeypatch.setattr(worker_tasks.httpx, "Client", _client_factory)

    input_file = tmp_path / "input.txt"
    input_file.write_text("worker input", encoding="utf-8")

    response = worker_tasks._call_engine_sync(
        engine_type="text",
        input_file_path=str(input_file),
        config={},
    )

    assert response == {"output": {"content": {"children": [{"text": "ok"}]}}}
    assert timeouts == [42]
    assert client.entered == 1
    assert client.exited == 1
    assert len(client.calls) == 1
    assert client.calls[0]["url"] == "http://text.test/process"


def test_call_engine_sync_includes_markitdown_file_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_engine_url="http://ocr.test",
            vlm_engine_url="http://vlm.test",
            text_engine_url="http://text.test",
            markitdown_engine_url="http://md.test",
        ),
    )

    class _TimeoutConfigStub:
        def resolve_timeout_seconds(self, engine_type: str, *, page_count: int = 1) -> int:
            _ = (engine_type, page_count)
            return 30

    monkeypatch.setattr(worker_tasks, "get_engine_timeout_config", lambda: _TimeoutConfigStub())

    client = _SyncClientStub(should_fail=False)
    monkeypatch.setattr(worker_tasks.httpx, "Client", lambda timeout: client)

    input_file = tmp_path / "input.html"
    input_file.write_text("<html><body>ok</body></html>", encoding="utf-8")

    response = worker_tasks._call_engine_sync(
        engine_type="markitdown",
        input_file_path=str(input_file),
        config={},
    )

    assert response == {"output": {"content": {"children": [{"text": "ok"}]}}}
    assert client.calls[0]["url"] == "http://md.test/process"
    payload = client.calls[0]["json"]
    assert isinstance(payload, dict)
    assert payload["file_extension"] == ".html"


def test_bound_celery_task_runs_adaptor_only_workflow_without_engine_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs, task_event_logs = _build_test_db(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")

    def _fake_execute_workflow_task_sync(
        task_run_id: str,
        workflow_def: dict[str, object],
        input_data: dict[str, object],
        context_data: dict[str, object] | None = None,
        *,
        enable_task_retry: bool = False,
        retry_count: int = 0,
        max_retries: int = worker_tasks.QUEUE_TASK_MAX_RETRIES,
    ) -> dict[str, object]:
        _ = (input_data, context_data, enable_task_retry, retry_count, max_retries)
        assert all(
            str(node.get("type")) != "engine/"
            for node in workflow_def.get("nodes", [])
            if isinstance(node, dict)
        )
        with session_factory() as session:
            worker_tasks._upsert_task_run(
                session,
                task_run_id=task_run_id,
                status="completed",
                updated_at=worker_tasks._now(),
            )
            worker_tasks._append_task_event(
                session,
                task_run_id=task_run_id,
                event_type="task_completed",
                payload={"task_id": task_run_id, "status": "completed"},
                created_at=worker_tasks._now(),
            )
            session.commit()
        return {"task_run_id": task_run_id, "status": "completed"}

    monkeypatch.setattr(
        worker_tasks,
        "execute_workflow_task_sync",
        _fake_execute_workflow_task_sync,
    )

    celery_app = Celery("test-docconv-adaptor-only")
    worker_tasks.register_worker_tasks(celery_app)
    task = celery_app.tasks[worker_tasks.EXECUTE_WORKFLOW_TASK_NAME]
    task.push_request(retries=0)
    task.max_retries = 3
    try:
        result = task.run(
            "task_adaptor_only",
            {
                "nodes": [
                    {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
                    {
                        "id": "adaptor_1",
                        "type": "processor/adaptor",
                        "config": {"code": "def main(inputs):\n    return {'text': 'ok'}"},
                    },
                    {"id": "end_1", "type": "end/final", "config": {}},
                ],
                "connections": [
                    {"source": "input_1", "target": "adaptor_1", "target_port": "input"},
                    {"source": "adaptor_1", "target": "end_1", "target_port": "input"},
                ],
            },
            {"input_1": {"file_path": str(tmp_path / "input.txt"), "filename": "input.txt"}},
            {"workspace_id": "ws_adaptor"},
        )
    finally:
        task.pop_request()

    assert result["status"] == "completed"
    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "task_adaptor_only")
            ).scalar_one()
            == "completed"
        )
        events = (
            session.execute(
                select(task_event_logs.c.event_type).where(
                    task_event_logs.c.task_run_id == "task_adaptor_only"
                )
            )
            .scalars()
            .all()
        )
        assert events == ["task_completed"]


def test_bound_celery_task_retry_uses_failed_adaptor_node_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _task_runs, _node_runs, _task_event_logs = _build_test_db(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)

    captured_retry: dict[str, object] = {}

    def _fake_execute_workflow_task_sync(*args, **kwargs):
        _ = (args, kwargs)
        raise EngineError(
            error_code=ErrorCode.ENGINE_TIMEOUT,
            message="Sandbox broker timed out",
            engine_name="processor/adaptor",
            details={"failed_node_id": "adaptor_1", "failed_node_type": "processor/adaptor"},
        )

    def _fake_retry_or_raise_engine_error(**kwargs):
        captured_retry.update(kwargs)
        raise RuntimeError("retry-called")

    monkeypatch.setattr(
        worker_tasks,
        "execute_workflow_task_sync",
        _fake_execute_workflow_task_sync,
    )
    monkeypatch.setattr(
        worker_tasks,
        "_retry_or_raise_engine_error",
        _fake_retry_or_raise_engine_error,
    )

    celery_app = Celery("test-docconv-adaptor-retry")
    worker_tasks.register_worker_tasks(celery_app)
    task = celery_app.tasks[worker_tasks.EXECUTE_WORKFLOW_TASK_NAME]
    task.push_request(retries=0)
    task.max_retries = 3
    try:
        with pytest.raises(RuntimeError, match="retry-called"):
            task.run(
                "task_adaptor_retry",
                {
                    "nodes": [
                        {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
                        {
                            "id": "adaptor_1",
                            "type": "processor/adaptor",
                            "config": {"code": "def main(inputs):\n    return {'text': 'ok'}"},
                        },
                    ],
                    "connections": [
                        {
                            "source": "input_1",
                            "target": "adaptor_1",
                            "target_port": "input",
                        }
                    ],
                },
                {"input_1": {"file_path": str(tmp_path / "input.txt"), "filename": "input.txt"}},
                {"workspace_id": "ws_adaptor"},
            )
    finally:
        task.pop_request()

    assert captured_retry["node_id"] == "adaptor_1"
    assert captured_retry["node_type"] == "processor/adaptor"
