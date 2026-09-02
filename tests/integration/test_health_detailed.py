from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.health as health_api
from app.main import app

OPERATOR_HEADERS = {"X-Operator-Token": "test-operator-health-token"}


def _patch_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.health.get_settings",
        lambda: SimpleNamespace(
            app_version="beta-1.0.0",
            ocr_engine_url="http://ocr:8002",
            vlm_engine_url="http://vlm:8003",
            text_engine_url="http://text:8004",
            markitdown_engine_url="http://markitdown:8005",
            layout_detection_engine_url="http://layout-detection:8006",
            image_enhancement_engine_url="http://image-enhancement:8008",
            image_rotation_engine_url="http://image-rotation:8009",
            operator_health_token="test-operator-health-token",
        ),
    )


@pytest.mark.asyncio
async def test_health_detailed_all_healthy(monkeypatch) -> None:
    _patch_settings(monkeypatch)
    monkeypatch.setattr("app.api.health.FeatureFlags.is_queue_mode", lambda: True)

    async def _engine_health(_settings):
        return {
            "ocr": {
                "status": "healthy",
                "latency_ms": 20,
                "version": "2.7.0",
                "url": "http://ocr:8002",
            },
            "vlm": {
                "status": "healthy",
                "latency_ms": 50,
                "version": "1.2.0",
                "url": "http://vlm:8003",
            },
            "text": {
                "status": "healthy",
                "latency_ms": 10,
                "version": "1.0.0",
                "url": "http://text:8004",
            },
            "markitdown": {
                "status": "healthy",
                "latency_ms": 12,
                "version": "1.0.0",
                "url": "http://markitdown:8005",
            },
        }

    monkeypatch.setattr(health_api, "_collect_engine_health_detailed", _engine_health)
    monkeypatch.setattr(
        "app.api.health.check_celery_health",
        lambda: asyncio.sleep(
            0,
            result={
                "status": "healthy",
                "active_workers": 2,
                "queued_tasks": 0,
                "latency_ms": 15,
            },
        ),
    )
    monkeypatch.setattr(
        "app.api.health.check_db_health",
        lambda: asyncio.sleep(0, result={"status": "healthy", "latency_ms": 3}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/internal/health/detailed", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "healthy"
    assert payload["version"] == "beta-1.0.0"
    assert payload["uptime_seconds"] >= 0
    assert payload["engines"]["ocr"]["status"] == "healthy"
    assert all("url" not in snapshot for snapshot in payload["engines"].values())
    assert "http://ocr:8002" not in response.text
    assert payload["celery"]["active_workers"] == 2
    assert payload["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_detailed_degraded_when_engine_slow(monkeypatch) -> None:
    _patch_settings(monkeypatch)
    monkeypatch.setattr("app.api.health.FeatureFlags.is_queue_mode", lambda: True)

    async def _engine_health(_settings):
        return {
            "ocr": {"status": "healthy", "latency_ms": 20, "url": "http://ocr:8002"},
            "vlm": {"status": "degraded", "latency_ms": 5200, "url": "http://vlm:8003"},
            "text": {"status": "healthy", "latency_ms": 10, "url": "http://text:8004"},
            "markitdown": {
                "status": "healthy",
                "latency_ms": 12,
                "url": "http://markitdown:8005",
            },
        }

    monkeypatch.setattr(health_api, "_collect_engine_health_detailed", _engine_health)
    monkeypatch.setattr(
        "app.api.health.check_celery_health",
        lambda: asyncio.sleep(
            0,
            result={
                "status": "healthy",
                "active_workers": 2,
                "queued_tasks": 1,
                "latency_ms": 9,
            },
        ),
    )
    monkeypatch.setattr(
        "app.api.health.check_db_health",
        lambda: asyncio.sleep(0, result={"status": "healthy", "latency_ms": 3}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/internal/health/detailed", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "degraded"
    assert payload["engines"]["vlm"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_detailed_unavailable_when_db_down(monkeypatch) -> None:
    _patch_settings(monkeypatch)
    monkeypatch.setattr("app.api.health.FeatureFlags.is_queue_mode", lambda: True)

    async def _engine_health(_settings):
        return {
            "ocr": {"status": "healthy", "latency_ms": 20, "url": "http://ocr:8002"},
            "vlm": {"status": "healthy", "latency_ms": 30, "url": "http://vlm:8003"},
            "text": {"status": "healthy", "latency_ms": 10, "url": "http://text:8004"},
            "markitdown": {
                "status": "healthy",
                "latency_ms": 12,
                "url": "http://markitdown:8005",
            },
        }

    monkeypatch.setattr(health_api, "_collect_engine_health_detailed", _engine_health)
    monkeypatch.setattr(
        "app.api.health.check_celery_health",
        lambda: asyncio.sleep(
            0,
            result={
                "status": "healthy",
                "active_workers": 1,
                "queued_tasks": 0,
                "latency_ms": 12,
            },
        ),
    )
    monkeypatch.setattr(
        "app.api.health.check_db_health",
        lambda: asyncio.sleep(0, result={"status": "unavailable", "latency_ms": 5000}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/internal/health/detailed", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "unavailable"
    assert payload["database"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_health_detailed_serial_mode_returns_null_celery(monkeypatch) -> None:
    _patch_settings(monkeypatch)
    monkeypatch.setattr("app.api.health.FeatureFlags.is_queue_mode", lambda: False)

    async def _engine_health(_settings):
        return {
            "ocr": {"status": "healthy", "latency_ms": 20, "url": "http://ocr:8002"},
            "vlm": {"status": "healthy", "latency_ms": 30, "url": "http://vlm:8003"},
            "text": {"status": "healthy", "latency_ms": 10, "url": "http://text:8004"},
            "markitdown": {
                "status": "healthy",
                "latency_ms": 12,
                "url": "http://markitdown:8005",
            },
        }

    monkeypatch.setattr(health_api, "_collect_engine_health_detailed", _engine_health)
    monkeypatch.setattr(
        "app.api.health.check_db_health",
        lambda: asyncio.sleep(0, result={"status": "healthy", "latency_ms": 2}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/internal/health/detailed", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "healthy"
    assert payload["celery"] is None


@pytest.mark.asyncio
async def test_health_detailed_engine_timeout_becomes_unavailable_without_blocking(
    monkeypatch,
) -> None:
    _patch_settings(monkeypatch)
    monkeypatch.setattr("app.api.health.HEALTH_CHECK_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("app.api.health.FeatureFlags.is_queue_mode", lambda: False)

    async def _probe_engine_detailed(*, engine_name: str, engine_url: str):
        if engine_name == "vlm":
            await asyncio.sleep(0.02)
            return {
                "status": "unavailable",
                "latency_ms": 20,
                "url": engine_url,
            }
        return {
            "status": "healthy",
            "latency_ms": 5,
            "url": engine_url,
        }

    monkeypatch.setattr(health_api, "_probe_engine_detailed", _probe_engine_detailed)
    monkeypatch.setattr(
        "app.api.health.check_db_health",
        lambda: asyncio.sleep(0, result={"status": "healthy", "latency_ms": 2}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/internal/health/detailed", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["engines"]["ocr"]["status"] == "healthy"
    assert payload["engines"]["text"]["status"] == "healthy"
    assert payload["engines"]["markitdown"]["status"] == "healthy"
    assert payload["engines"]["vlm"]["status"] == "unavailable"
    assert payload["overall"] == "degraded"
