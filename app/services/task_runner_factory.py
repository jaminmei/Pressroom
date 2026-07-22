from __future__ import annotations

from typing import Awaitable, Callable

from celery import Celery

from app.core.feature_flags import FeatureFlags, OrchestratorMode
from app.models.task import TaskContext
from app.services.node_registry import NodeRegistryService
from app.services.queue_task_runner import QueueTaskRunner
from app.services.task_runner import SerialTaskRunner
from app.services.task_runner_base import TaskRunnerBase
from app.worker import create_celery_app

EventPublisher = Callable[[str, TaskContext, dict[str, object]], Awaitable[None]]


class TaskRunnerFactory:
    """Build task runners based on orchestrator mode feature flags."""

    def __init__(
        self,
        *,
        event_publisher: EventPublisher,
        celery_app: Celery | None = None,
        node_registry: NodeRegistryService | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._celery_app = celery_app
        self._node_registry = node_registry

    def create(self) -> TaskRunnerBase:
        mode = FeatureFlags.get_orchestrator_mode()
        if mode == OrchestratorMode.SERIAL:
            return SerialTaskRunner(
                self._event_publisher,
            )
        if mode == OrchestratorMode.QUEUE:
            return QueueTaskRunner(self._resolve_celery_app())
        raise ValueError(f"Unsupported orchestrator mode: {mode}")

    def _resolve_celery_app(self) -> Celery:
        if self._celery_app is None:
            self._celery_app = create_celery_app()
        return self._celery_app
