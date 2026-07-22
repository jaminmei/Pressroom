from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.health as health_api


def test_probe_engine_returns_healthy_with_latency() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.health.httpx.AsyncClient", return_value=mock_client):
        status, latency_ms = asyncio.run(
            health_api._probe_engine_http(engine_name="ocr", engine_url="http://ocr:8000")
        )

    assert status == "healthy"
    assert isinstance(latency_ms, int)
    assert latency_ms >= 0


def test_probe_engine_marks_timeout_for_slow_engine() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.health.httpx.AsyncClient", return_value=mock_client):
        status, latency_ms = asyncio.run(
            health_api._probe_engine_http(engine_name="ocr", engine_url="http://ocr:8000")
        )

    assert status == "timeout"
    assert isinstance(latency_ms, int)
    assert latency_ms >= 0


def test_collect_engine_health_returns_name_status_latency_and_closes_adapters() -> None:
    engine_map = {
        "ocr": "http://ocr:8000",
        "vlm": "http://vlm:8000",
    }

    with (
        patch.object(health_api, "_engine_urls", return_value=engine_map),
        patch.object(
            health_api,
            "_probe_engine_http",
            new=AsyncMock(
                side_effect=[
                    ("healthy", 10),
                    ("unhealthy", 25),
                ]
            ),
        ),
    ):
        engines = asyncio.run(health_api._collect_engine_health(MagicMock()))

    assert [engine["name"] for engine in engines] == ["ocr", "vlm"]
    assert [engine["status"] for engine in engines] == ["healthy", "unhealthy"]
    assert all(isinstance(engine["latency_ms"], int) for engine in engines)


def test_get_health_is_liveness_only_and_does_not_probe_engines() -> None:
    app = FastAPI()
    app.include_router(health_api.router, prefix="/api")
    collect = AsyncMock(side_effect=AssertionError("liveness must not probe engines"))

    with (
        patch("app.api.health.get_settings", return_value=MagicMock(app_version="1.0.0")),
        patch.object(health_api, "_collect_engine_health", collect),
    ):
        with TestClient(app) as client:
            response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "healthy"
    assert payload["status"] == "healthy"
    assert payload["engines"] == []
    assert payload["components"]["engines"] == {}
    collect.assert_not_awaited()
