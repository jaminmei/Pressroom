from __future__ import annotations

from typing import Any

from app.services.queue_task_runner import QueueTaskRunner
from app.services.task_runner import SerialTaskRunner
from app.services.task_runner_factory import TaskRunnerFactory


class _CeleryStub:
    def send_task(self, name: str, args: list[object]) -> None:
        _ = (name, args)


async def _publish_event(event_type: str, context: object, data: dict[str, object]) -> None:
    _ = (event_type, context, data)


def _build_factory(*, celery_app: Any | None = None) -> TaskRunnerFactory:
    return TaskRunnerFactory(
        event_publisher=_publish_event,
        celery_app=celery_app,  # type: ignore[arg-type]
    )


def test_factory_returns_serial_runner_when_orchestrator_mode_is_serial(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "serial")
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    runner = _build_factory(celery_app=_CeleryStub()).create()

    assert isinstance(runner, SerialTaskRunner)


def test_factory_returns_queue_runner_when_orchestrator_mode_is_queue(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "false")

    runner = _build_factory(celery_app=_CeleryStub()).create()

    assert isinstance(runner, QueueTaskRunner)


def test_factory_returns_queue_runner_for_enable_queue_mode_compat(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    runner = _build_factory(celery_app=_CeleryStub()).create()

    assert isinstance(runner, QueueTaskRunner)


def test_factory_lazy_creates_and_reuses_default_celery_app(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "queue")
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)

    created: list[_CeleryStub] = []

    def _fake_create_celery_app() -> _CeleryStub:
        instance = _CeleryStub()
        created.append(instance)
        return instance

    monkeypatch.setattr(
        "app.services.task_runner_factory.create_celery_app",
        _fake_create_celery_app,
    )

    factory = _build_factory()
    first = factory.create()
    second = factory.create()

    assert isinstance(first, QueueTaskRunner)
    assert isinstance(second, QueueTaskRunner)
    assert len(created) == 1
