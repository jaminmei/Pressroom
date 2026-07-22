from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("values must not be empty")
    if len(ordered) == 1:
        return ordered[0]

    rank = (percentile / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def calculate_latency_metrics(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    return {
        "p50_ms": round(_percentile(latencies_ms, 50), 2),
        "p95_ms": round(_percentile(latencies_ms, 95), 2),
        "p99_ms": round(_percentile(latencies_ms, 99), 2),
    }


def calculate_completion_rate(*, total: int, succeeded: int) -> float:
    if total <= 0:
        return 0.0
    return round(succeeded / total, 4)


def _read_latency_metrics(report: Mapping[str, object]) -> dict[str, float]:
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        return {}
    metrics = summary.get("latency_metrics")
    if not isinstance(metrics, Mapping):
        return {}

    normalized: dict[str, float] = {}
    for key in ("p50_ms", "p95_ms", "p99_ms"):
        value = metrics.get(key)
        if isinstance(value, int | float):
            normalized[key] = round(float(value), 2)
    return normalized


def _read_peak_memory(report: Mapping[str, object]) -> dict[str, float]:
    memory = report.get("memory")
    if not isinstance(memory, Mapping):
        return {}
    peak_values = memory.get("peak_by_container_mb")
    if not isinstance(peak_values, Mapping):
        return {}

    normalized: dict[str, float] = {}
    for key, value in peak_values.items():
        if isinstance(key, str) and isinstance(value, int | float):
            normalized[key] = round(float(value), 2)
    return normalized


def build_mode_comparison(
    *,
    current_report: Mapping[str, object],
    baseline_report: Mapping[str, object],
) -> dict[str, object]:
    current_metrics = _read_latency_metrics(current_report)
    baseline_metrics = _read_latency_metrics(baseline_report)
    latency_delta_ms = {
        key: round(current_metrics[key] - baseline_metrics[key], 2)
        for key in current_metrics.keys() & baseline_metrics.keys()
    }

    current_memory = _read_peak_memory(current_report)
    baseline_memory = _read_peak_memory(baseline_report)
    memory_peak_delta_mb = {
        key: round(current_memory[key] - baseline_memory[key], 2)
        for key in current_memory.keys() & baseline_memory.keys()
    }

    current_summary = current_report.get("summary")
    baseline_summary = baseline_report.get("summary")

    current_completion_value = (
        current_summary.get("completion_rate") if isinstance(current_summary, Mapping) else None
    )
    baseline_completion_value = (
        baseline_summary.get("completion_rate") if isinstance(baseline_summary, Mapping) else None
    )
    current_completion = (
        float(current_completion_value)
        if isinstance(current_completion_value, int | float)
        else 0.0
    )
    baseline_completion = (
        float(baseline_completion_value)
        if isinstance(baseline_completion_value, int | float)
        else 0.0
    )

    return {
        "current_mode": current_report.get("mode", "unknown"),
        "baseline_mode": baseline_report.get("mode", "unknown"),
        "latency_delta_ms": latency_delta_ms,
        "memory_peak_delta_mb": memory_peak_delta_mb,
        "completion_rate_delta": round(current_completion - baseline_completion, 4),
    }


def write_json_report(report_dir: Path, filename: str, payload: Mapping[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / filename
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
