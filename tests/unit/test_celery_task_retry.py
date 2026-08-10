from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast

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
from app.models.execution import NodeOutput
from app.services.dag_scheduler import DAGRunResult


@dataclass
class _RetryRequestStub:
    retries: int


class _TaskSelfStub:
    def __init__(self, *, retries: int, max_retries: int = 3) -> None:
        self.request = cast(worker_tasks._RetryRequest, _RetryRequestStub(retries=retries))
        self.max_retries = max_retries
        self.retry_calls: list[tuple[Exception, int | None]] = []

    def retry(self, *, exc: Exception, countdown: int | None = None) -> NoReturn:
        self.retry_calls.append((exc, countdown))
        raise RuntimeError("retry-invoked")


def test_register_worker_tasks_sets_retry_related_task_options() -> None:
    celery_app = Celery("test-docconv-retry")
    worker_tasks.register_worker_tasks(celery_app)

    task = celery_app.tasks[worker_tasks.EXECUTE_WORKFLOW_TASK_NAME]

    assert task.max_retries == 3
    assert task.default_retry_delay == 5
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


@pytest.mark.parametrize(
    ("retries", "expected_delay_seconds"),
    [
        (0, 5),
        (1, 10),
        (2, 20),
    ],
)
def test_retry_or_raise_engine_error_calls_self_retry_for_retryable_error(
    monkeypatch,
    retries: int,
    expected_delay_seconds: int,
) -> None:
    task_self = _TaskSelfStub(retries=retries, max_retries=3)
    error = EngineError(
        error_code=ErrorCode.ENGINE_TIMEOUT,
        message="timeout",
        engine_name="ocr",
    )
    captured_events: list[dict[str, object]] = []

    def _fake_append_node_retry_event(
        *,
        task_run_id: str,
        node_id: str,
        node_type: str,
        retry_count: int,
        max_retries: int,
        next_retry_delay_ms: int,
        error: EngineError,
    ) -> None:
        captured_events.append(
            {
                "task_run_id": task_run_id,
                "node_id": node_id,
                "node_type": node_type,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "next_retry_delay_ms": next_retry_delay_ms,
                "error_code": error.error_code.value,
            }
        )

    monkeypatch.setattr(worker_tasks, "_append_node_retry_event", _fake_append_node_retry_event)

    with pytest.raises(RuntimeError, match="retry-invoked"):
        worker_tasks._retry_or_raise_engine_error(
            task_self=task_self,
            error=error,
            task_run_id="task-001",
            node_id="engine_1",
            node_type="engine/ocr",
        )

    assert len(task_self.retry_calls) == 1
    assert task_self.retry_calls[0][1] == expected_delay_seconds
    assert len(captured_events) == 1
    assert captured_events[0]["retry_count"] == retries + 1
    assert captured_events[0]["max_retries"] == 3
    assert captured_events[0]["next_retry_delay_ms"] == expected_delay_seconds * 1000
    assert captured_events[0]["error_code"] == "ENGINE_TIMEOUT"


def test_retry_or_raise_engine_error_raises_directly_for_non_retryable_error() -> None:
    task_self = _TaskSelfStub(retries=0, max_retries=3)
    error = EngineError(
        error_code=ErrorCode.ENGINE_INVALID_RESPONSE,
        message="invalid response",
        engine_name="ocr",
    )

    with pytest.raises(EngineError) as exc_info:
        worker_tasks._retry_or_raise_engine_error(
            task_self=task_self,
            error=error,
            task_run_id="task-001",
            node_id="engine_1",
            node_type="engine/ocr",
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_INVALID_RESPONSE
    assert task_self.retry_calls == []


def test_retry_or_raise_engine_error_raises_directly_after_max_retries() -> None:
    task_self = _TaskSelfStub(retries=3, max_retries=3)
    error = EngineError(
        error_code=ErrorCode.ENGINE_UNREACHABLE,
        message="unreachable",
        engine_name="ocr",
    )

    with pytest.raises(EngineError) as exc_info:
        worker_tasks._retry_or_raise_engine_error(
            task_self=task_self,
            error=error,
            task_run_id="task-001",
            node_id="engine_1",
            node_type="engine/ocr",
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_UNREACHABLE
    assert task_self.retry_calls == []


def test_execute_workflow_task_retries_when_durable_dag_returns_retryable_adaptor_failure(
    tmp_path,
    monkeypatch,
) -> None:
    from cryptography.fernet import Fernet
    from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, create_engine
    from sqlalchemy.orm import sessionmaker

    db_file = tmp_path / "retryable-adaptor.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()
    Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("workspace_id", String),
        Column("duration_ms", Integer),
        Column("node_summary_json", Text),
        Column("result_preview", Text),
        Column("results_json", Text),
        Column("error", Text),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    Table(
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
    metadata.create_all(engine)

    monkeypatch.setattr(
        worker_tasks,
        "SessionLocal",
        sessionmaker(bind=engine, expire_on_commit=False),
    )
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: Fernet.generate_key())

    def _fake_execute_workflow_sync(**kwargs):
        _ = kwargs
        return DAGRunResult(
            completed={"input_1": NodeOutput(text="ok")},
            failed={"adaptor_1": "Sandbox broker timed out"},
            skipped=set(),
            failure_causes={
                "adaptor_1": EngineError(
                    error_code=ErrorCode.ENGINE_TIMEOUT,
                    message="Sandbox broker timed out",
                    engine_name="processor/adaptor",
                )
            },
        )

    monkeypatch.setattr(worker_tasks, "execute_workflow_sync", _fake_execute_workflow_sync)

    with pytest.raises(EngineError) as exc_info:
        worker_tasks.execute_workflow_task_sync(
            "task-adaptor-retry",
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
            {
                "input_1": {
                    "file_path": str(tmp_path / "input.txt"),
                    "filename": "input.txt",
                    "mime_type": "text/plain",
                    "workspace_id": "ws_retry",
                }
            },
            context_data={"workspace_id": "ws_retry"},
            enable_task_retry=True,
            retry_count=0,
            max_retries=3,
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_TIMEOUT


def test_execute_workflow_task_finalizes_non_retryable_adaptor_failure(
    tmp_path,
    monkeypatch,
) -> None:
    from cryptography.fernet import Fernet
    from sqlalchemy import (
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

    db_file = tmp_path / "terminal-adaptor.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("workspace_id", String),
        Column("duration_ms", Integer),
        Column("node_summary_json", Text),
        Column("result_preview", Text),
        Column("results_json", Text),
        Column("error", Text),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    Table(
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
    metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: Fernet.generate_key())

    def _fake_execute_workflow_sync(**kwargs):
        _ = kwargs
        return DAGRunResult(
            completed={"input_1": NodeOutput(text="ok")},
            failed={"adaptor_1": "Sandbox broker returned an invalid response"},
            skipped=set(),
            failure_causes={
                "adaptor_1": EngineError(
                    error_code=ErrorCode.ENGINE_INVALID_RESPONSE,
                    message="Sandbox broker returned an invalid response",
                    engine_name="processor/adaptor",
                )
            },
        )

    monkeypatch.setattr(worker_tasks, "execute_workflow_sync", _fake_execute_workflow_sync)

    result = worker_tasks.execute_workflow_task_sync(
        "task-adaptor-terminal",
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
                "workspace_id": "ws_retry",
            }
        },
        context_data={"workspace_id": "ws_retry"},
        enable_task_retry=True,
        retry_count=0,
        max_retries=3,
    )

    assert result["status"] == "failed"
    with session_factory() as session:
        stored_status = session.execute(
            select(task_runs.c.status).where(task_runs.c.id == "task-adaptor-terminal")
        ).scalar_one()
        assert stored_status == "failed"


def test_bound_celery_retry_persists_running_and_retry_without_terminal_failure(
    tmp_path,
    monkeypatch,
) -> None:
    db_file = tmp_path / "retry-boundary.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("error", Text),
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
        Column("error", Text),
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
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)

    def _fake_execute_workflow_task_sync(*args, **kwargs):
        _ = (args, kwargs)
        raise EngineError(
            error_code=ErrorCode.ENGINE_TIMEOUT,
            message="Sandbox broker timed out",
            engine_name="processor/adaptor",
            details={"failed_node_id": "adaptor_1", "failed_node_type": "processor/adaptor"},
        )

    monkeypatch.setattr(
        worker_tasks,
        "execute_workflow_task_sync",
        _fake_execute_workflow_task_sync,
    )

    class _TaskSelf:
        def __init__(self) -> None:
            self.request = cast(worker_tasks._RetryRequest, _RetryRequestStub(retries=0))
            self.max_retries = 3

        def retry(self, *, exc: Exception, countdown: int | None = None) -> NoReturn:
            with session_factory() as session:
                assert (
                    session.execute(
                        select(task_runs.c.status).where(task_runs.c.id == "task-boundary")
                    ).scalar_one()
                    == "running"
                )
                assert (
                    session.execute(
                        select(task_runs.c.error).where(task_runs.c.id == "task-boundary")
                    ).scalar_one()
                    is None
                )
                node = session.execute(
                    select(node_runs.c.node_id, node_runs.c.node_type, node_runs.c.status).where(
                        node_runs.c.task_run_id == "task-boundary"
                    )
                ).one()
                assert node.node_id == "adaptor_1"
                assert node.node_type == "processor/adaptor"
                assert node.status == "running"
                events = (
                    session.execute(
                        select(task_event_logs.c.event_type).where(
                            task_event_logs.c.task_run_id == "task-boundary"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert "node_retry" in events
                assert "task_failed" not in events
            raise RuntimeError("retry-invoked")

    celery_app = Celery("test-docconv-boundary")
    worker_tasks.register_worker_tasks(celery_app)
    task = celery_app.tasks[worker_tasks.EXECUTE_WORKFLOW_TASK_NAME]
    helper = _TaskSelf()
    task.push_request(retries=0)
    task.max_retries = 3
    task.retry = helper.retry
    try:
        with pytest.raises(RuntimeError, match="retry-invoked"):
            task.run(
                "task-boundary",
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
                {"workspace_id": "ws_retry"},
            )
    finally:
        task.pop_request()


def test_bound_celery_retry_uses_adaptor_node_fallback_when_error_has_no_failed_node_details(
    tmp_path,
    monkeypatch,
) -> None:
    db_file = tmp_path / "retry-adaptor-fallback.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("error", Text),
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
        Column("error", Text),
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
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)

    def _fake_execute_workflow_task_sync(*args, **kwargs):
        _ = (args, kwargs)
        raise EngineError(
            error_code=ErrorCode.ENGINE_TIMEOUT,
            message="Sandbox broker timed out",
            engine_name="processor/adaptor",
        )

    monkeypatch.setattr(
        worker_tasks,
        "execute_workflow_task_sync",
        _fake_execute_workflow_task_sync,
    )

    class _TaskSelf:
        def __init__(self) -> None:
            self.request = cast(worker_tasks._RetryRequest, _RetryRequestStub(retries=0))
            self.max_retries = 3

        def retry(self, *, exc: Exception, countdown: int | None = None) -> NoReturn:
            assert isinstance(exc, EngineError)
            with session_factory() as session:
                assert (
                    session.execute(
                        select(task_runs.c.status).where(task_runs.c.id == "task-adaptor-fallback")
                    ).scalar_one()
                    == "running"
                )
                node = session.execute(
                    select(node_runs.c.node_id, node_runs.c.node_type, node_runs.c.status).where(
                        node_runs.c.task_run_id == "task-adaptor-fallback"
                    )
                ).one()
                assert node.node_id == "adaptor_1"
                assert node.node_type == "processor/adaptor"
                assert node.status == "running"
                retry_event = session.execute(
                    select(task_event_logs.c.payload).where(
                        task_event_logs.c.task_run_id == "task-adaptor-fallback",
                        task_event_logs.c.event_type == "node_retry",
                    )
                ).scalar_one()
                assert retry_event["node_id"] == "adaptor_1"
                assert retry_event["node_type"] == "processor/adaptor"
            raise RuntimeError("retry-invoked")

    celery_app = Celery("test-docconv-adaptor-fallback")
    worker_tasks.register_worker_tasks(celery_app)
    task = celery_app.tasks[worker_tasks.EXECUTE_WORKFLOW_TASK_NAME]
    helper = _TaskSelf()
    task.push_request(retries=0)
    task.max_retries = 3
    task.retry = helper.retry
    try:
        with pytest.raises(RuntimeError, match="retry-invoked"):
            task.run(
                "task-adaptor-fallback",
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
                {"workspace_id": "ws_retry"},
            )
    finally:
        task.pop_request()
