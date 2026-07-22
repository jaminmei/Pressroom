from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast

import pytest
from celery import Celery

import app.worker_tasks as worker_tasks
from app.errors import EngineError, ErrorCode


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
