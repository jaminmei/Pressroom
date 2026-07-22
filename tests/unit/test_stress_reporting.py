from __future__ import annotations

from pathlib import Path

from app.services.stress_reporting import (
    build_mode_comparison,
    calculate_completion_rate,
    calculate_latency_metrics,
    write_json_report,
)


def test_calculate_latency_metrics_returns_interpolated_percentiles() -> None:
    metrics = calculate_latency_metrics([100.0, 200.0, 300.0, 400.0, 500.0])

    assert metrics == {
        "p50_ms": 300.0,
        "p95_ms": 480.0,
        "p99_ms": 496.0,
    }


def test_calculate_completion_rate_returns_fraction() -> None:
    assert calculate_completion_rate(total=5, succeeded=5) == 1.0
    assert calculate_completion_rate(total=5, succeeded=4) == 0.8
    assert calculate_completion_rate(total=0, succeeded=0) == 0.0


def test_build_mode_comparison_includes_latency_and_memory_deltas() -> None:
    current_report = {
        "mode": "serial",
        "summary": {
            "completion_rate": 1.0,
            "success_count": 5,
            "total_tasks": 5,
            "latency_metrics": {"p50_ms": 2000.0, "p95_ms": 3200.0, "p99_ms": 3500.0},
        },
        "memory": {
            "peak_by_container_mb": {
                "backend": 256.0,
                "celery-worker": 300.0,
            }
        },
    }
    baseline_report = {
        "mode": "queue",
        "summary": {
            "completion_rate": 1.0,
            "success_count": 5,
            "total_tasks": 5,
            "latency_metrics": {"p50_ms": 1800.0, "p95_ms": 2800.0, "p99_ms": 3000.0},
        },
        "memory": {
            "peak_by_container_mb": {
                "backend": 240.0,
                "celery-worker": 280.0,
            }
        },
    }

    comparison = build_mode_comparison(
        current_report=current_report,
        baseline_report=baseline_report,
    )

    assert comparison["current_mode"] == "serial"
    assert comparison["baseline_mode"] == "queue"
    assert comparison["latency_delta_ms"] == {
        "p50_ms": 200.0,
        "p95_ms": 400.0,
        "p99_ms": 500.0,
    }
    assert comparison["memory_peak_delta_mb"] == {
        "backend": 16.0,
        "celery-worker": 20.0,
    }


def test_write_json_report_persists_payload(tmp_path: Path) -> None:
    payload = {"mode": "queue", "summary": {"completion_rate": 1.0}}

    report_path = write_json_report(tmp_path, "report.json", payload)

    assert report_path == tmp_path / "report.json"
    assert report_path.read_text(encoding="utf-8") == (
        '{\n  "mode": "queue",\n  "summary": {\n    "completion_rate": 1.0\n  }\n}'
    )
