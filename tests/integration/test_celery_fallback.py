from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
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

import app.worker_tasks as worker_tasks
from app.errors import EngineError, ErrorCode


@pytest.fixture()
def db_env(tmp_path: Path):
    db_file = tmp_path / "celery_fallback.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    metadata = MetaData()

    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
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
        Column("payload", Text, nullable=True),
        Column("created_at", DateTime(timezone=False)),
    )
    metadata.create_all(engine)

    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return factory, task_runs, node_runs, task_event_logs


def _workflow_with_fallback() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {
                "id": "engine_1",
                "type": "engine/vlm",
                "config": {
                    "prompt": "convert",
                    "fallback_engine": "ocr",
                    "fallback_config": {"language": "ch"},
                },
            },
            {"id": "output_1", "type": "output/markdown", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }


def test_queue_fallback_writes_node_fallback_event_and_completes(
    db_env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs, task_event_logs = db_env
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

    call_order: list[str] = []

    def _fake_call_engine_sync(
        *,
        engine_type: str,
        input_file_path: str,
        config: dict[str, object],
    ):
        _ = input_file_path
        call_order.append(engine_type)
        if engine_type == "vlm":
            raise EngineError(
                error_code=ErrorCode.ENGINE_TIMEOUT,
                message="vlm timeout",
                engine_name="vlm",
            )
        if engine_type == "ocr":
            assert config == {"language": "ch"}
            return {"output": {"content": {"children": [{"text": "ok"}]}}}
        raise AssertionError(f"unexpected engine_type={engine_type}")

    monkeypatch.setattr(worker_tasks, "_call_engine_sync", _fake_call_engine_sync)
    monkeypatch.setattr(
        worker_tasks,
        "_is_engine_healthy_sync",
        lambda engine_type: engine_type == "ocr",
    )

    input_file = tmp_path / "input.txt"
    input_file.write_text("fallback input", encoding="utf-8")

    result = worker_tasks.execute_workflow_task_sync(
        "task_celery_fallback_success",
        _workflow_with_fallback(),
        {"input_1": {"file_path": str(input_file), "filename": "input.txt"}},
        enable_task_retry=True,
        retry_count=3,
        max_retries=3,
    )

    assert result["status"] == "completed"
    assert result["engine_type"] == "ocr"
    assert result["fallback_from"] == "vlm"
    assert call_order == ["vlm", "ocr"]

    with session_factory() as session:
        task_status = session.execute(
            select(task_runs.c.status).where(task_runs.c.id == "task_celery_fallback_success")
        ).scalar_one()
        assert task_status == "completed"

        events = session.execute(
            select(task_event_logs.c.event_type, task_event_logs.c.payload).where(
                task_event_logs.c.task_run_id == "task_celery_fallback_success"
            )
        ).all()
        event_types = [item.event_type for item in events]
        assert "node_fallback" in event_types
        assert event_types[-2:] == ["node_completed", "task_completed"]

        fallback_payload = next(
            item.payload for item in events if item.event_type == "node_fallback"
        )
        assert '"reason": "ENGINE_TIMEOUT"' in str(fallback_payload)
        assert '"original_engine": "engine/vlm"' in str(fallback_payload)
        assert '"fallback_engine": "engine/ocr"' in str(fallback_payload)


def test_queue_fallback_skips_when_fallback_engine_unhealthy(
    db_env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs, task_event_logs = db_env
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

    def _always_fail_primary(*, engine_type: str, input_file_path: str, config: dict[str, object]):
        _ = (input_file_path, config)
        assert engine_type == "vlm"
        raise EngineError(
            error_code=ErrorCode.ENGINE_TIMEOUT,
            message="vlm timeout",
            engine_name="vlm",
        )

    monkeypatch.setattr(worker_tasks, "_call_engine_sync", _always_fail_primary)
    monkeypatch.setattr(worker_tasks, "_is_engine_healthy_sync", lambda engine_type: False)

    input_file = tmp_path / "input.txt"
    input_file.write_text("fallback input", encoding="utf-8")

    with pytest.raises(EngineError) as exc_info:
        worker_tasks.execute_workflow_task_sync(
            "task_celery_fallback_unhealthy",
            _workflow_with_fallback(),
            {"input_1": {"file_path": str(input_file), "filename": "input.txt"}},
            enable_task_retry=True,
            retry_count=3,
            max_retries=3,
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_TIMEOUT

    with session_factory() as session:
        task_status = session.execute(
            select(task_runs.c.status).where(task_runs.c.id == "task_celery_fallback_unhealthy")
        ).scalar_one()
        assert task_status == "failed"

        event_types = (
            session.execute(
                select(task_event_logs.c.event_type).where(
                    task_event_logs.c.task_run_id == "task_celery_fallback_unhealthy"
                )
            )
            .scalars()
            .all()
        )
        assert "node_fallback" not in event_types
        assert event_types[-2:] == ["node_failed", "task_failed"]


def test_queue_does_not_fallback_on_non_retryable_error(
    db_env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs, task_event_logs = db_env
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

    call_order: list[str] = []

    def _fail_non_retryable(*, engine_type: str, input_file_path: str, config: dict[str, object]):
        _ = (input_file_path, config)
        call_order.append(engine_type)
        raise EngineError(
            error_code=ErrorCode.ENGINE_INVALID_RESPONSE,
            message="invalid response",
            engine_name=engine_type,
        )

    monkeypatch.setattr(worker_tasks, "_call_engine_sync", _fail_non_retryable)
    monkeypatch.setattr(worker_tasks, "_is_engine_healthy_sync", lambda engine_type: True)

    input_file = tmp_path / "input.txt"
    input_file.write_text("fallback input", encoding="utf-8")

    with pytest.raises(EngineError) as exc_info:
        worker_tasks.execute_workflow_task_sync(
            "task_celery_no_fallback_non_retryable",
            _workflow_with_fallback(),
            {"input_1": {"file_path": str(input_file), "filename": "input.txt"}},
            enable_task_retry=True,
            retry_count=3,
            max_retries=3,
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_INVALID_RESPONSE
    assert call_order == ["vlm"]

    with session_factory() as session:
        task_status = session.execute(
            select(task_runs.c.status).where(
                task_runs.c.id == "task_celery_no_fallback_non_retryable"
            )
        ).scalar_one()
        assert task_status == "failed"

        event_types = (
            session.execute(
                select(task_event_logs.c.event_type).where(
                    task_event_logs.c.task_run_id == "task_celery_no_fallback_non_retryable"
                )
            )
            .scalars()
            .all()
        )
        assert "node_fallback" not in event_types
        assert event_types[-2:] == ["node_failed", "task_failed"]
