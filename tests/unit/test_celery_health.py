from __future__ import annotations

import asyncio
import time

import pytest

import app.api.health as health_api
import app.services.celery_health as celery_health
from app.celery_queues import REQUIRED_CELERY_QUEUES


class _InspectStub:
    def __init__(
        self,
        *,
        active_queues: object,
        active: object,
        ping: object | None = None,
        delay: float = 0.0,
    ) -> None:
        self._active_queues = active_queues
        self._active = active
        self._ping = ping
        self._delay = delay

    def active_queues(self) -> object:
        if self._delay:
            time.sleep(self._delay)
        return self._active_queues

    def active(self) -> object:
        if self._delay:
            time.sleep(self._delay)
        return self._active

    def ping(self) -> object:
        if self._delay:
            time.sleep(self._delay)
        return self._ping


class _ControlStub:
    def __init__(self, inspect_stub: _InspectStub) -> None:
        self._inspect_stub = inspect_stub

    def inspect(self, timeout: float) -> _InspectStub:
        _ = timeout
        return self._inspect_stub


class _CeleryAppStub:
    def __init__(self, inspect_stub: _InspectStub) -> None:
        self.control = _ControlStub(inspect_stub)


@pytest.mark.asyncio
async def test_check_celery_health_reports_healthy_with_workers_and_tasks() -> None:
    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues={"worker-a": [{"name": "default"}], "worker-b": [{"name": "default"}]},
            active={"worker-a": [{"id": "task-1"}], "worker-b": [{"id": "task-2"}]},
        )
    )

    result = await celery_health.check_celery_health(celery_app)

    assert result["status"] == "degraded"
    assert result["active_workers"] == 2
    assert result["queued_tasks"] == 2
    assert result["required_queues"] == list(REQUIRED_CELERY_QUEUES)
    assert result["missing_queues"] == ["celery", "workflow", "evaluation"]


@pytest.mark.asyncio
async def test_check_celery_health_marks_unavailable_when_no_workers() -> None:
    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues=None,
            active=None,
        )
    )

    result = await celery_health.check_celery_health(celery_app)

    assert result["status"] == "unavailable"
    assert result["active_workers"] == 0
    assert result["queued_tasks"] == 0


@pytest.mark.asyncio
async def test_check_celery_health_timeout_returns_unavailable(monkeypatch) -> None:
    def _slow_probe(_celery_app, _inspect_timeout_seconds: float) -> tuple[int, int]:
        time.sleep(0.05)
        return (1, 0)

    monkeypatch.setattr(celery_health, "_probe_celery_sync", _slow_probe)

    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues={"worker-a": [{"name": "default"}]},
            active={"worker-a": []},
        )
    )

    result = await celery_health.check_celery_health(celery_app, timeout_seconds=0.01)

    assert result["status"] == "unavailable"
    assert result["active_workers"] == 0
    assert result["queued_tasks"] == 0


@pytest.mark.asyncio
async def test_check_celery_health_uses_ping_fallback_when_worker_lists_are_empty() -> None:
    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues=None,
            active=None,
            ping={"worker-a": {"ok": "pong"}},
        )
    )

    result = await celery_health.check_celery_health(celery_app)

    assert result["status"] == "degraded"
    assert result["active_workers"] == 1
    assert result["queued_tasks"] == 0
    assert result["missing_queues"] == list(REQUIRED_CELERY_QUEUES)


@pytest.mark.asyncio
async def test_check_celery_health_allows_multi_call_probe_budget(monkeypatch) -> None:
    async def _delayed_to_thread(_fn, *_args):
        await asyncio.sleep(0.05)
        return (1, 0, set(REQUIRED_CELERY_QUEUES))

    monkeypatch.setattr(celery_health.asyncio, "to_thread", _delayed_to_thread)

    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues={"worker-a": [{"name": "default"}]},
            active={"worker-a": []},
            ping={"worker-a": {"ok": "pong"}},
        )
    )

    result = await celery_health.check_celery_health(celery_app, timeout_seconds=0.02)

    assert result["status"] == "healthy"
    assert result["active_workers"] == 1
    assert result["queued_tasks"] == 0


@pytest.mark.asyncio
async def test_check_celery_health_is_healthy_when_all_required_queues_are_subscribed() -> None:
    celery_app = _CeleryAppStub(
        _InspectStub(
            active_queues={
                "worker-a": [{"name": queue} for queue in REQUIRED_CELERY_QUEUES],
            },
            active={"worker-a": []},
        )
    )

    result = await celery_health.check_celery_health(celery_app)

    assert result["status"] == "healthy"
    assert result["missing_queues"] == []


@pytest.mark.asyncio
async def test_worker_health_exposes_required_and_missing_queues(monkeypatch) -> None:
    monkeypatch.setattr(
        health_api.FeatureFlags,
        "get_orchestrator_mode",
        lambda: type("Mode", (), {"value": "queue"})(),
    )

    async def _health():
        return {
            "status": "degraded",
            "active_workers": 1,
            "queued_tasks": 0,
            "required_queues": list(REQUIRED_CELERY_QUEUES),
            "missing_queues": ["evaluation"],
        }

    monkeypatch.setattr(health_api, "check_celery_health", _health)
    payload = await health_api.get_worker_health()

    assert payload["mode"] == "queue"
    assert payload["workers"]["required_queues"] == list(REQUIRED_CELERY_QUEUES)  # type: ignore[index]
    assert payload["workers"]["missing_queues"] == ["evaluation"]  # type: ignore[index]
