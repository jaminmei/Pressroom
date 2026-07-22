from __future__ import annotations

import asyncio

import pytest

import app.services.db_health as db_health


@pytest.mark.asyncio
async def test_check_db_health_success(monkeypatch) -> None:
    async def _ok_probe() -> None:
        return None

    monkeypatch.setattr(db_health, "_probe_db_once", _ok_probe)

    result = await db_health.check_db_health()

    assert result["status"] == "healthy"
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_check_db_health_failure(monkeypatch) -> None:
    async def _fail_probe() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db_health, "_probe_db_once", _fail_probe)

    result = await db_health.check_db_health()

    assert result["status"] == "unavailable"
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_check_db_health_timeout(monkeypatch) -> None:
    async def _slow_probe() -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(db_health, "_probe_db_once", _slow_probe)

    result = await db_health.check_db_health(timeout_seconds=0.01)

    assert result["status"] == "unavailable"
    assert result["latency_ms"] >= 0
