from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

import app.worker_tasks as worker_tasks

REPORT_DIR = Path("tests/benchmark/.reports")


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


def _calc_metrics(latencies_ms: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(_percentile(latencies_ms, 50), 2),
        "p95_ms": round(_percentile(latencies_ms, 95), 2),
        "p99_ms": round(_percentile(latencies_ms, 99), 2),
    }


def _get_required_input_file(env_key: str = "PERF_BENCHMARK_INPUT_FILE") -> Path:
    if os.getenv("RUN_PERFORMANCE_BENCHMARKS", "0") != "1":
        pytest.skip("Set RUN_PERFORMANCE_BENCHMARKS=1 to run performance benchmarks.")

    raw_path = os.getenv(env_key, "").strip()
    if not raw_path:
        pytest.skip(f"Set {env_key} to a valid test document path.")

    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        pytest.skip(f"{env_key} does not exist: {path}")
    return path


def _parse_engine_config(engine_type: str) -> dict[str, object]:
    env_key = f"PERF_BENCHMARK_{engine_type.upper()}_CONFIG_JSON"
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {env_key}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{env_key} must be a JSON object.")
    return parsed


def _ensure_engine_available(engine_type: str) -> None:
    try:
        engine_url = worker_tasks._resolve_engine_url(engine_type)
        with httpx.Client(timeout=3) as client:
            response = client.get(f"{engine_url}/health")
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{engine_type} engine healthcheck failed: {exc}")


def _run_benchmark(
    *,
    engine_type: str,
    input_file: Path,
    iterations: int,
    config: dict[str, object],
) -> list[float]:
    latencies_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        worker_tasks._call_engine_sync(
            engine_type=engine_type,
            input_file_path=str(input_file),
            config=config,
        )
        duration_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(duration_ms)
    return latencies_ms


def _write_report(entry: dict[str, object]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "performance_report.jsonl"
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


@pytest.mark.parametrize(
    ("engine_type", "target_p95_ms"),
    [
        ("ocr", 30_000),
        ("vlm", 60_000),
    ],
)
def test_engine_latency_benchmark(engine_type: str, target_p95_ms: int) -> None:
    input_file = _get_required_input_file()
    _ensure_engine_available(engine_type)

    iterations = int(os.getenv("PERF_BENCHMARK_ITERATIONS", "5"))
    if iterations < 3:
        raise ValueError("PERF_BENCHMARK_ITERATIONS must be >= 3 for percentile statistics.")

    config = {"page_count": 1, **_parse_engine_config(engine_type)}
    latencies_ms = _run_benchmark(
        engine_type=engine_type,
        input_file=input_file,
        iterations=iterations,
        config=config,
    )
    metrics = _calc_metrics(latencies_ms)
    report_entry = {
        "engine_type": engine_type,
        "input_file": str(input_file),
        "iterations": iterations,
        "target_p95_ms": target_p95_ms,
        "metrics": metrics,
        "raw_samples_ms": [round(sample, 2) for sample in latencies_ms],
    }
    baseline_env_key = f"PERF_BASELINE_{engine_type.upper()}_P95_MS"
    raw_baseline = os.getenv(baseline_env_key, "").strip()
    baseline_p95_ms: float | None = None
    if raw_baseline:
        baseline_p95_ms = float(raw_baseline)
        report_entry["baseline_p95_ms"] = baseline_p95_ms
        report_entry["p95_delta_ms"] = round(metrics["p95_ms"] - baseline_p95_ms, 2)

    _write_report(report_entry)
    print(json.dumps(report_entry, ensure_ascii=False))

    assert metrics["p50_ms"] > 0
    assert metrics["p95_ms"] >= metrics["p50_ms"]
    assert metrics["p99_ms"] >= metrics["p95_ms"]

    if os.getenv("ENFORCE_PERFORMANCE_SLO", "0") == "1":
        assert metrics["p95_ms"] < target_p95_ms
    if baseline_p95_ms is not None and os.getenv("ENFORCE_PERFORMANCE_REGRESSION", "0") == "1":
        assert metrics["p95_ms"] <= baseline_p95_ms


def test_ocr_ten_page_latency_benchmark() -> None:
    input_file = _get_required_input_file("PERF_BENCHMARK_OCR_10P_INPUT_FILE")
    _ensure_engine_available("ocr")

    iterations = int(os.getenv("PERF_BENCHMARK_ITERATIONS", "5"))
    if iterations < 3:
        raise ValueError("PERF_BENCHMARK_ITERATIONS must be >= 3 for percentile statistics.")

    config = {"page_count": 10, **_parse_engine_config("ocr")}
    latencies_ms = _run_benchmark(
        engine_type="ocr",
        input_file=input_file,
        iterations=iterations,
        config=config,
    )
    metrics = _calc_metrics(latencies_ms)
    report_entry = {
        "engine_type": "ocr",
        "scenario": "ten_page",
        "input_file": str(input_file),
        "iterations": iterations,
        "target_p95_ms": 180_000,
        "metrics": metrics,
        "raw_samples_ms": [round(sample, 2) for sample in latencies_ms],
    }
    raw_baseline = os.getenv("PERF_BASELINE_OCR_10P_P95_MS", "").strip()
    baseline_p95_ms: float | None = None
    if raw_baseline:
        baseline_p95_ms = float(raw_baseline)
        report_entry["baseline_p95_ms"] = baseline_p95_ms
        report_entry["p95_delta_ms"] = round(metrics["p95_ms"] - baseline_p95_ms, 2)

    _write_report(report_entry)
    print(json.dumps(report_entry, ensure_ascii=False))

    assert metrics["p50_ms"] > 0
    assert metrics["p95_ms"] >= metrics["p50_ms"]
    assert metrics["p99_ms"] >= metrics["p95_ms"]

    if os.getenv("ENFORCE_PERFORMANCE_SLO", "0") == "1":
        assert metrics["p95_ms"] < 180_000
    if baseline_p95_ms is not None and os.getenv("ENFORCE_PERFORMANCE_REGRESSION", "0") == "1":
        assert metrics["p95_ms"] <= baseline_p95_ms
