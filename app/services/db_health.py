from __future__ import annotations

import asyncio
from time import perf_counter

from sqlalchemy import text
from typing_extensions import TypedDict

DEFAULT_DB_HEALTH_TIMEOUT_SECONDS = 5.0


class DatabaseHealthSnapshot(TypedDict):
    status: str
    latency_ms: int


async def _probe_db_once() -> None:
    # Lazy import avoids DB engine/session initialization at module import time.
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))


async def check_db_health(
    *,
    timeout_seconds: float = DEFAULT_DB_HEALTH_TIMEOUT_SECONDS,
) -> DatabaseHealthSnapshot:
    started_at = perf_counter()

    try:
        await asyncio.wait_for(_probe_db_once(), timeout=timeout_seconds)
    except Exception:
        status = "unavailable"
    else:
        status = "healthy"

    latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
    return {
        "status": status,
        "latency_ms": latency_ms,
    }
