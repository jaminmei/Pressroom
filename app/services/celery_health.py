from __future__ import annotations

import asyncio
from time import perf_counter

from celery import Celery
from typing_extensions import TypedDict

from app.celery_queues import REQUIRED_CELERY_QUEUES

DEFAULT_CELERY_INSPECT_TIMEOUT_SECONDS = 3.0


class CeleryHealthSnapshot(TypedDict):
    status: str
    active_workers: int
    queued_tasks: int
    required_queues: list[str]
    missing_queues: list[str]


def _count_active_workers(active_queues: object, active_tasks: object) -> int:
    worker_names: set[str] = set()
    if isinstance(active_queues, dict):
        worker_names.update(str(name) for name in active_queues.keys())
    if isinstance(active_tasks, dict):
        worker_names.update(str(name) for name in active_tasks.keys())
    return len(worker_names)


def _count_active_tasks(active_tasks: object) -> int:
    if not isinstance(active_tasks, dict):
        return 0

    total = 0
    for tasks in active_tasks.values():
        if isinstance(tasks, list):
            total += len(tasks)
    return total


def _collect_active_queue_names(active_queues: object) -> set[str]:
    queue_names: set[str] = set()
    if not isinstance(active_queues, dict):
        return queue_names

    for queues in active_queues.values():
        if not isinstance(queues, list):
            continue
        for queue in queues:
            if not isinstance(queue, dict):
                continue
            name = queue.get("name")
            if isinstance(name, str) and name:
                queue_names.add(name)
    return queue_names


def _probe_celery_sync(
    celery_app: Celery,
    inspect_timeout_seconds: float,
) -> tuple[int, int, set[str]]:
    inspect = celery_app.control.inspect(timeout=inspect_timeout_seconds)
    ping_result = inspect.ping()
    active_queues = inspect.active_queues()
    active_tasks = inspect.active()
    active_workers = _count_active_workers(active_queues, active_tasks)
    if active_workers == 0 and isinstance(ping_result, dict):
        active_workers = len(ping_result)
    queued_tasks = _count_active_tasks(active_tasks)
    return active_workers, queued_tasks, _collect_active_queue_names(active_queues)


def _build_default_celery_app() -> Celery:
    # Lazy import avoids pulling worker/db initialization during module import.
    from app.worker import create_celery_app

    return create_celery_app()


async def check_celery_health(
    celery_app: Celery | None = None,
    *,
    timeout_seconds: float = DEFAULT_CELERY_INSPECT_TIMEOUT_SECONDS,
) -> CeleryHealthSnapshot:
    app = celery_app or _build_default_celery_app()
    started_at = perf_counter()
    required_queues = list(REQUIRED_CELERY_QUEUES)

    try:
        active_workers, queued_tasks, active_queues = await asyncio.wait_for(
            asyncio.to_thread(_probe_celery_sync, app, timeout_seconds),
            timeout=max(timeout_seconds * 3.5, timeout_seconds + 0.01),
        )
    except Exception:
        active_workers = 0
        queued_tasks = 0
        active_queues = set()
        status = "unavailable"
    else:
        missing_queues = [queue for queue in required_queues if queue not in active_queues]
        if active_workers < 1:
            status = "unavailable"
        elif missing_queues:
            status = "degraded"
        else:
            status = "healthy"

    _ = max(int((perf_counter() - started_at) * 1000), 0)
    missing_queues = [queue for queue in required_queues if queue not in active_queues]
    return {
        "status": status,
        "active_workers": active_workers,
        "queued_tasks": queued_tasks,
        "required_queues": required_queues,
        "missing_queues": missing_queues,
    }
