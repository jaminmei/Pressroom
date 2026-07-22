from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.api.health as health_api


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_api.router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_health_is_process_liveness_with_service_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        health_api,
        "get_settings",
        lambda: SimpleNamespace(app_version="1.0.0"),
    )
    collector = AsyncMock(side_effect=AssertionError("must not probe engines"))
    monkeypatch.setattr(health_api, "_collect_engine_health", collector)

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["overall"] == "healthy"
    assert payload["version"] == "1.0.0"
    assert payload["engines"] == []
    assert "timestamp" in payload
    collector.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_response_contains_no_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        health_api,
        "get_settings",
        lambda: SimpleNamespace(app_version="1.0.0"),
    )
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert "url" not in response.text.lower()
    assert "endpoint" not in response.text.lower()
