from __future__ import annotations

import asyncio
import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import SecretStr
from typing_extensions import TypedDict

from app.config import Settings, get_settings
from app.core.feature_flags import FeatureFlags
from app.services.celery_health import check_celery_health
from app.services.db_health import check_db_health

router = APIRouter()
HEALTH_CHECK_TIMEOUT_SECONDS = 5
ENGINE_DEGRADED_LATENCY_MS = 5000
_APP_STARTED_AT = perf_counter()
_operator_token_header = APIKeyHeader(
    name="X-Operator-Token",
    auto_error=False,
    scheme_name="OperatorHealthToken",
)


def require_operator_health(
    supplied_token: Annotated[str | None, Security(_operator_token_header)],
) -> None:
    configured = get_settings().operator_health_token
    expected = configured.get_secret_value() if isinstance(configured, SecretStr) else configured
    if not expected or not supplied_token or not hmac.compare_digest(expected, supplied_token):
        raise HTTPException(status_code=404, detail="Not found")


setattr(require_operator_health, "policy_kind", "operator")  # noqa: B010


@router.get("/internal/health/worker", include_in_schema=False)
async def get_worker_health(
    _: Annotated[None, Security(require_operator_health)],
) -> dict[str, object]:
    mode = FeatureFlags.get_orchestrator_mode()
    if mode.value != "queue":
        return {"workers": {}, "mode": "serial"}
    celery = await check_celery_health()
    return {
        "mode": "queue",
        "workers": {
            "active_count": celery["active_workers"],
            "status": celery["status"],
            "queued_tasks": celery["queued_tasks"],
            "required_queues": celery["required_queues"],
            "missing_queues": celery["missing_queues"],
        },
    }


class EngineHealth(TypedDict):
    name: str
    status: str
    latency_ms: int


class EngineDetailedHealth(TypedDict, total=False):
    status: str
    latency_ms: int
    version: str


@router.get("/health")
async def get_health() -> dict[str, object]:
    """Return process liveness without probing engines or user providers."""
    settings = get_settings()
    return {
        "overall": "healthy",
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.app_version,
        "engines": [],
        "components": {
            "api": "healthy",
            "storage": "healthy",
            "engines": {},
        },
    }


@router.get("/internal/health/detailed", include_in_schema=False)
async def get_health_detailed(
    _: Annotated[None, Security(require_operator_health)],
) -> dict[str, object]:
    settings = get_settings()

    if FeatureFlags.is_queue_mode():
        engines, celery, database = await asyncio.gather(
            _collect_engine_health_detailed(settings),
            check_celery_health(),
            check_db_health(),
        )
    else:
        engines, database = await asyncio.gather(
            _collect_engine_health_detailed(settings),
            check_db_health(),
        )
        celery = None

    engines = {name: _sanitize_engine_snapshot(snapshot) for name, snapshot in engines.items()}
    engine_statuses = {
        engine_name: str(engine_info.get("status", "unknown"))
        for engine_name, engine_info in engines.items()
    }

    celery_status: str | None = None
    celery_active_workers: int | None = None
    if celery is not None:
        celery_status = str(celery["status"])
        celery_active_workers = int(celery["active_workers"])

    overall = calculate_overall_status(
        engine_statuses=engine_statuses,
        database_status=str(database["status"]),
        celery_status=celery_status,
        celery_active_workers=celery_active_workers,
    )

    return {
        "overall": overall,
        "version": settings.app_version,
        "uptime_seconds": max(int(perf_counter() - _APP_STARTED_AT), 0),
        "engines": engines,
        "celery": celery,
        "database": database,
    }


def _sanitize_engine_snapshot(snapshot: Mapping[str, object]) -> EngineDetailedHealth:
    """Keep detailed health useful without returning configured endpoints."""
    sanitized: EngineDetailedHealth = {}
    status = snapshot.get("status")
    latency_ms = snapshot.get("latency_ms")
    version = snapshot.get("version")
    if isinstance(status, str):
        sanitized["status"] = status
    if isinstance(latency_ms, int) and not isinstance(latency_ms, bool):
        sanitized["latency_ms"] = latency_ms
    if isinstance(version, str):
        sanitized["version"] = version
    return sanitized


def calculate_overall_status(
    *,
    engine_statuses: dict[str, str],
    database_status: str,
    celery_status: str | None = None,
    celery_active_workers: int | None = None,
) -> str:
    if database_status != "healthy":
        return "unavailable"
    if any(status != "healthy" for status in engine_statuses.values()):
        return "degraded"
    if celery_status is not None:
        if celery_status != "healthy":
            return "degraded"
        if celery_active_workers == 0:
            return "degraded"
    return "healthy"


async def _collect_engine_health(settings: Settings) -> list[EngineHealth]:
    engines = _engine_urls(settings)
    checks = await asyncio.gather(
        *(_probe_engine_http(engine_name=name, engine_url=url) for name, url in engines.items())
    )
    return [
        {"name": name, "status": status, "latency_ms": latency_ms}
        for name, (status, latency_ms) in zip(engines.keys(), checks, strict=True)
    ]


async def _probe_engine_http(*, engine_name: str, engine_url: str) -> tuple[str, int]:
    _ = engine_name
    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await asyncio.wait_for(
                client.get(f"{engine_url}/health"),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
        status = "healthy" if response.status_code == 200 else "unhealthy"
    except (asyncio.TimeoutError, httpx.TimeoutException):
        status = "timeout"
    except Exception:
        status = "unhealthy"

    latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
    return (status, latency_ms)


def _engine_urls(settings: Settings) -> dict[str, str]:
    return {
        "ocr": settings.ocr_engine_url,
        "vlm": settings.vlm_engine_url,
        "text": settings.text_engine_url,
        "markitdown": settings.markitdown_engine_url,
        "layout_detection": settings.layout_detection_engine_url,
        "image_enhancement": settings.image_enhancement_engine_url,
        "image_rotation": settings.image_rotation_engine_url,
    }


async def _collect_engine_health_detailed(settings: Settings) -> dict[str, EngineDetailedHealth]:
    engines = _engine_urls(settings)
    checks = await asyncio.gather(
        *(
            _probe_engine_detailed(engine_name=engine_name, engine_url=engine_url)
            for engine_name, engine_url in engines.items()
        )
    )
    return {
        engine_name: snapshot for engine_name, snapshot in zip(engines.keys(), checks, strict=True)
    }


async def _probe_engine_detailed(*, engine_name: str, engine_url: str) -> EngineDetailedHealth:
    _ = engine_name
    started_at = perf_counter()

    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await asyncio.wait_for(
                client.get(f"{engine_url}/health"),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
    except Exception:
        latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
        return {
            "status": "unavailable",
            "latency_ms": latency_ms,
        }

    latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
    if response.status_code != 200:
        return {
            "status": "unavailable",
            "latency_ms": latency_ms,
        }

    status = "degraded" if latency_ms >= ENGINE_DEGRADED_LATENCY_MS else "healthy"
    snapshot: EngineDetailedHealth = {
        "status": status,
        "latency_ms": latency_ms,
    }

    version = _extract_engine_version(response)
    if version is not None:
        snapshot["version"] = version

    return snapshot


def _extract_engine_version(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None

    if not isinstance(payload, dict):
        return None

    for key in ("version", "engine_version"):
        raw_version = payload.get(key)
        if isinstance(raw_version, (str, int, float)):
            return str(raw_version)

    meta = payload.get("meta")
    if isinstance(meta, dict):
        raw_version = meta.get("version")
        if isinstance(raw_version, (str, int, float)):
            return str(raw_version)

    return None
