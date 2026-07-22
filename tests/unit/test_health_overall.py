from __future__ import annotations

from app.api.health import calculate_overall_status


def test_calculate_overall_status_healthy_when_all_components_ok() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy", "vlm": "healthy", "text": "healthy"},
        database_status="healthy",
        celery_status="healthy",
        celery_active_workers=2,
    )

    assert overall == "healthy"


def test_calculate_overall_status_unavailable_when_db_down() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy"},
        database_status="unavailable",
        celery_status="healthy",
        celery_active_workers=1,
    )

    assert overall == "unavailable"


def test_calculate_overall_status_degraded_when_any_engine_not_healthy() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy", "vlm": "degraded"},
        database_status="healthy",
    )

    assert overall == "degraded"


def test_calculate_overall_status_degraded_when_celery_unavailable() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy", "vlm": "healthy"},
        database_status="healthy",
        celery_status="unavailable",
        celery_active_workers=0,
    )

    assert overall == "degraded"


def test_calculate_overall_status_degraded_when_celery_has_zero_workers() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy", "vlm": "healthy"},
        database_status="healthy",
        celery_status="healthy",
        celery_active_workers=0,
    )

    assert overall == "degraded"


def test_calculate_overall_status_ignores_celery_when_none() -> None:
    overall = calculate_overall_status(
        engine_statuses={"ocr": "healthy", "vlm": "healthy"},
        database_status="healthy",
        celery_status=None,
        celery_active_workers=None,
    )

    assert overall == "healthy"
