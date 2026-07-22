from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.health as health_api


def test_liveness_remains_healthy_when_engine_state_changes() -> None:
    app = FastAPI()
    app.include_router(health_api.router, prefix="/api")
    collector = AsyncMock(return_value=[{"name": "vlm", "status": "unhealthy", "latency_ms": 10}])
    with (
        patch.object(health_api, "_collect_engine_health", collector),
        patch.object(
            health_api,
            "get_settings",
            return_value=MagicMock(app_version="1.0.0"),
        ),
        TestClient(app) as client,
    ):
        responses = [client.get("/api/health") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["status"] == "healthy" for response in responses)
    assert all(response.json()["engines"] == [] for response in responses)
    collector.assert_not_awaited()
