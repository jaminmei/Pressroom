from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Generator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

import httpx
import psutil
import pytest

from app.services.stress_reporting import (
    build_mode_comparison,
    calculate_completion_rate,
    calculate_latency_metrics,
    write_json_report,
)

REPORT_DIR = Path("tests/stress/.reports")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("STRESS_TASK_TIMEOUT_SECONDS", "180"))
POLL_INTERVAL_SECONDS = float(os.getenv("STRESS_POLL_INTERVAL_SECONDS", "1.0"))
MEMORY_SAMPLE_INTERVAL_SECONDS = float(os.getenv("STRESS_MEMORY_SAMPLE_INTERVAL_SECONDS", "5"))
SUCCESS_STATUSES = {"completed", "partial_completed"}
TERMINAL_STATUSES = SUCCESS_STATUSES | {"failed", "cancelled"}
MEMORY_UNITS_TO_MB = {
    "b": 1 / (1024 * 1024),
    "kib": 1 / 1024,
    "kb": 1 / 1000,
    "mib": 1.0,
    "mb": 1.0,
    "gib": 1024.0,
    "gb": 1000.0,
}
SCENARIO_SLO_MS = {
    "ocr_only": {"p50_ms": 15_000.0, "p95_ms": 30_000.0, "p99_ms": 45_000.0},
    "vlm_only": {"p50_ms": 30_000.0, "p95_ms": 60_000.0, "p99_ms": 90_000.0},
}
REPORT_SCHEMA_VERSION = 1
FIXTURE_PROFILE = "engine-compatible-v1"


@dataclass(frozen=True)
class StressTaskSpec:
    scenario: str
    engine: str
    filename: str
    content_type: str
    content: bytes
    output_format: str = "markdown"


@dataclass
class StressTaskResult:
    scenario: str
    engine: str
    filename: str
    content_type: str
    mode: str
    task_id: str | None
    status: str
    started_at: str
    completed_at: str
    duration_ms: float
    poll_count: int
    result_count: int
    error: str | None = None
    results_url: str | None = None
    download_urls: list[str] | None = None


@pytest.fixture(autouse=True)
def _clear_runtime_caches() -> Generator[None, None, None]:
    if _use_external_backend():
        yield
        return

    if os.getenv("RUN_STRESS_TESTS", "0") != "1" and not os.getenv("POSTGRES_PASSWORD"):
        yield
        return

    from app.api.tasks import get_task_run_repository, reset_task_orchestrator
    from app.config import get_settings
    from app.config.celery_config import get_celery_settings

    get_settings.cache_clear()
    get_celery_settings.cache_clear()
    reset_task_orchestrator()
    get_task_run_repository.cache_clear()
    yield
    get_task_run_repository.cache_clear()
    reset_task_orchestrator()
    get_celery_settings.cache_clear()
    get_settings.cache_clear()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_mode() -> str:
    raw_mode = os.getenv("ORCHESTRATOR_MODE", "serial").strip().lower()
    return raw_mode or "serial"


def _get_base_url() -> str:
    raw_base_url = os.getenv("STRESS_TEST_BASE_URL", "").strip()
    return raw_base_url.rstrip("/") if raw_base_url else "http://testserver"


def _get_concurrency() -> int:
    return max(int(os.getenv("STRESS_TASK_CONCURRENCY", "5")), 1)


def _use_external_backend() -> bool:
    return bool(os.getenv("STRESS_TEST_BASE_URL", "").strip())


def _require_live_run_enabled() -> None:
    if os.getenv("RUN_STRESS_TESTS", "0") != "1":
        pytest.skip("Set RUN_STRESS_TESTS=1 to run the live concurrent stress suite.")

    if _use_external_backend():
        return

    if not os.getenv("POSTGRES_PASSWORD"):
        pytest.skip("Set POSTGRES_PASSWORD to run local ASGI stress tests.")


def _build_single_page_pdf_bytes(label: str) -> bytes:
    stream = f"BT /F1 18 Tf 36 120 Td ({label}) Tj ET".encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%b\nendstream" % (len(stream), stream),
    ]

    lines = [b"%PDF-1.4\n"]
    offsets: list[int] = [0]
    current = len(lines[0])
    for index, obj in enumerate(objects, start=1):
        offsets.append(current)
        entry = b"%d 0 obj\n%b\nendobj\n" % (index, obj)
        lines.append(entry)
        current += len(entry)

    xref_offset = current
    xref_lines = [b"xref\n", b"0 %d\n" % (len(objects) + 1), b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%EOF\n") % (
        len(objects) + 1,
        xref_offset,
    )
    return b"".join(lines + xref_lines + [trailer])


def _build_text_bytes(label: str) -> bytes:
    return (
        f"{label}\nDocument Conversion\nStress fixture for concurrent task execution.\n"
    ).encode("utf-8")


def _build_mixed_task_specs() -> list[StressTaskSpec]:
    return [
        StressTaskSpec(
            scenario="mixed",
            engine="ocr",
            filename="stress-ocr-a.pdf",
            content_type="application/pdf",
            content=_build_single_page_pdf_bytes("Stress OCR A"),
        ),
        StressTaskSpec(
            scenario="mixed",
            engine="ocr",
            filename="stress-ocr-b.pdf",
            content_type="application/pdf",
            content=_build_single_page_pdf_bytes("Stress OCR B"),
        ),
        StressTaskSpec(
            scenario="mixed",
            engine="vlm",
            filename="stress-vlm.pdf",
            content_type="application/pdf",
            content=_build_single_page_pdf_bytes("Stress VLM"),
        ),
        StressTaskSpec(
            scenario="mixed",
            engine="text",
            filename="stress-input.txt",
            content_type="text/plain",
            content=_build_text_bytes("Stress Text"),
        ),
        StressTaskSpec(
            scenario="mixed",
            engine="markitdown",
            filename="stress-markitdown.pdf",
            content_type="application/pdf",
            content=_build_single_page_pdf_bytes("Stress MarkItDown"),
        ),
    ]


def _build_single_engine_specs(engine: str) -> list[StressTaskSpec]:
    if engine not in {"ocr", "vlm"}:
        raise ValueError(f"Unsupported single-engine stress scenario: {engine}")

    scenario = f"{engine}_only"
    return [
        StressTaskSpec(
            scenario=scenario,
            engine=engine,
            filename=f"stress-{engine}-{index}.pdf",
            content_type="application/pdf",
            content=_build_single_page_pdf_bytes(f"{engine.upper()} {index}"),
        )
        for index in range(1, 6)
    ]


@asynccontextmanager
async def _build_async_client() -> Any:
    if _use_external_backend():
        async with httpx.AsyncClient(
            base_url=_get_base_url(),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        ) as client:
            yield client
        return

    from app.api.tasks import get_task_run_repository, reset_task_orchestrator
    from app.config import get_settings
    from app.config.celery_config import get_celery_settings
    from app.main import app

    get_settings.cache_clear()
    get_celery_settings.cache_clear()
    reset_task_orchestrator()
    get_task_run_repository.cache_clear()

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=_get_base_url(),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        ) as client:
            yield client
    finally:
        get_settings.cache_clear()
        get_celery_settings.cache_clear()
        reset_task_orchestrator()
        get_task_run_repository.cache_clear()


async def _ensure_backend_available(
    client: httpx.AsyncClient,
    *,
    required_engines: set[str],
) -> None:
    operator_token = os.getenv("OPERATOR_HEALTH_TOKEN")
    if not operator_token:
        pytest.skip("OPERATOR_HEALTH_TOKEN is required for detailed stress preflight")
    try:
        response = await client.get(
            "/api/internal/health/detailed",
            headers={"X-Operator-Token": operator_token},
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Stress backend is unavailable at {_get_base_url()}: {exc}")

    payload = response.json()
    if not isinstance(payload, dict):
        pytest.skip("Detailed health endpoint returned an unexpected payload.")

    database = payload.get("database")
    if isinstance(database, dict) and database.get("status") == "unavailable":
        pytest.skip("Database is unavailable; cannot run concurrent stress suite.")

    engines = payload.get("engines")
    if isinstance(engines, dict):
        unavailable = [
            engine_name
            for engine_name in sorted(required_engines)
            if isinstance(engines.get(engine_name), dict)
            and engines[engine_name].get("status") == "unavailable"
        ]
        if unavailable:
            joined = ", ".join(unavailable)
            pytest.skip(f"Required engines unavailable for stress suite: {joined}")

    if _get_mode() == "queue" and _use_external_backend():
        celery = payload.get("celery")
        if not isinstance(celery, dict) or celery.get("status") != "healthy":
            pytest.skip("Queue mode stress suite requires a healthy Celery worker.")

    if _get_mode() == "queue" and not _use_external_backend():
        if not await asyncio.to_thread(_has_local_queue_worker):
            pytest.skip("Queue mode stress suite requires a reachable local Celery worker.")


def _has_local_queue_worker() -> bool:
    from app.worker import create_celery_app

    inspect = create_celery_app().control.inspect(timeout=3.0)
    response = inspect.ping()
    return isinstance(response, dict) and len(response) >= 1


async def _poll_terminal_status(
    client: httpx.AsyncClient,
    task_id: str,
    *,
    timeout_seconds: float,
) -> tuple[dict[str, Any], int]:
    deadline = time.monotonic() + timeout_seconds
    polls = 0
    while time.monotonic() < deadline:
        response = await client.get(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        response.raise_for_status()
        polls += 1
        payload = response.json()
        if isinstance(payload, dict):
            status = payload.get("status")
            if isinstance(status, str) and status in TERMINAL_STATUSES:
                return payload, polls
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    raise AssertionError(f"Task did not reach terminal state within timeout: {task_id}")


async def _poll_results_ready(
    client: httpx.AsyncClient,
    task_id: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.get(f"/api/tasks/{task_id}/results")
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        elif response.status_code not in {409, 503}:
            response.raise_for_status()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    raise AssertionError(f"Task results were not ready within timeout: {task_id}")


def _parse_memory_mb(raw_value: str) -> float | None:
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)", raw_value)
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    factor = MEMORY_UNITS_TO_MB.get(unit)
    if factor is None:
        return None
    return round(amount * factor, 2)


def _docker_service_filters() -> tuple[str, ...]:
    raw_filters = os.getenv(
        "STRESS_TEST_DOCKER_SERVICES",
        "backend,celery-worker,ocr-engine,vlm-engine,text-engine,markitdown-engine",
    )
    return tuple(item.strip() for item in raw_filters.split(",") if item.strip())


def _collect_docker_memory_sample() -> dict[str, float]:
    filters = _docker_service_filters()
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{ json . }}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    samples: dict[str, float] = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            continue
        name = payload.get("Name")
        memory_usage = payload.get("MemUsage")
        if not isinstance(name, str) or not isinstance(memory_usage, str):
            continue
        if filters and not any(token in name for token in filters):
            continue
        current_usage = memory_usage.split("/", 1)[0].strip()
        value_mb = _parse_memory_mb(current_usage)
        if value_mb is not None:
            samples[name] = value_mb
    return samples


def _collect_process_memory_sample() -> dict[str, float]:
    process = psutil.Process(os.getpid())
    rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    return {"pytest_process": rss_mb}


def _select_memory_collector() -> tuple[str, Callable[[], dict[str, float]]]:
    raw_source = os.getenv("STRESS_MEMORY_SOURCE", "auto").strip().lower() or "auto"
    if raw_source == "process":
        return "process", _collect_process_memory_sample
    if raw_source == "docker":
        return "docker", _collect_docker_memory_sample
    if shutil.which("docker"):
        return "docker", _collect_docker_memory_sample
    return "process", _collect_process_memory_sample


async def _monitor_memory(stop_event: asyncio.Event) -> dict[str, object]:
    source, collector = _select_memory_collector()
    samples: list[dict[str, object]] = []
    fallback_error: str | None = None

    while not stop_event.is_set():
        try:
            containers = collector()
        except Exception as exc:  # noqa: BLE001
            if source == "docker":
                fallback_error = str(exc)
                source = "process"
                collector = _collect_process_memory_sample
                containers = collector()
            else:
                return {
                    "available": False,
                    "source": source,
                    "sample_count": len(samples),
                    "peak_by_container_mb": {},
                    "samples": samples,
                    "error": str(exc),
                }

        samples.append(
            {
                "captured_at": _utcnow_iso(),
                "source": source,
                "containers": containers,
            }
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=MEMORY_SAMPLE_INTERVAL_SECONDS)
        except TimeoutError:
            continue

    peak_by_container: dict[str, float] = {}
    for sample in samples:
        containers_value = sample.get("containers")
        if not isinstance(containers_value, dict):
            continue
        for name, value in containers_value.items():
            if isinstance(name, str) and isinstance(value, int | float):
                peak_by_container[name] = max(peak_by_container.get(name, 0.0), float(value))

    return {
        "available": True,
        "source": source,
        "sample_count": len(samples),
        "peak_by_container_mb": {k: round(v, 2) for k, v in sorted(peak_by_container.items())},
        "samples": samples,
        "error": fallback_error,
    }


async def _run_single_task(
    client: httpx.AsyncClient,
    spec: StressTaskSpec,
    semaphore: asyncio.Semaphore,
) -> StressTaskResult:
    mode = _get_mode()
    async with semaphore:
        started_at = _utcnow_iso()
        started = time.perf_counter()
        task_id: str | None = None
        try:
            response = await client.post(
                "/api/tasks",
                files={"file": (spec.filename, spec.content, spec.content_type)},
                data={"engine": spec.engine, "output_format": spec.output_format},
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            task_id_value = payload.get("task_id")
            if not isinstance(task_id_value, str) or not task_id_value:
                raise AssertionError(f"Invalid task creation payload for {spec.engine}: {payload}")
            task_id = task_id_value

            status_payload, poll_count = await _poll_terminal_status(
                client,
                task_id,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            )
            status = str(status_payload.get("status", "unknown"))
            results_url: str | None = f"/api/tasks/{task_id}/results"
            result_count = 0
            download_urls: list[str] = []

            if status in SUCCESS_STATUSES:
                results_payload = await _poll_results_ready(
                    client,
                    task_id,
                    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                )
                results = results_payload.get("results", [])
                if isinstance(results, list):
                    result_count = len(results)
                    download_urls = [
                        str(item["download_url"])
                        for item in results
                        if isinstance(item, dict) and isinstance(item.get("download_url"), str)
                    ]
            else:
                results_url = None

            completed_at = _utcnow_iso()
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return StressTaskResult(
                scenario=spec.scenario,
                engine=spec.engine,
                filename=spec.filename,
                content_type=spec.content_type,
                mode=mode,
                task_id=task_id,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                poll_count=poll_count,
                result_count=result_count,
                error=(
                    status_payload.get("error")
                    if isinstance(status_payload.get("error"), str)
                    else None
                ),
                results_url=results_url,
                download_urls=download_urls,
            )
        except Exception as exc:  # noqa: BLE001
            completed_at = _utcnow_iso()
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return StressTaskResult(
                scenario=spec.scenario,
                engine=spec.engine,
                filename=spec.filename,
                content_type=spec.content_type,
                mode=mode,
                task_id=task_id,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                poll_count=0,
                result_count=0,
                error=str(exc),
                results_url=None,
                download_urls=[],
            )


def _report_path(scenario: str, mode: str) -> Path:
    return REPORT_DIR / f"concurrent_tasks_{scenario}_{mode}.json"


def _comparison_report_path(current_mode: str, baseline_mode: str, scenario: str) -> Path:
    return REPORT_DIR / (
        f"concurrent_tasks_comparison_{scenario}_{current_mode}_vs_{baseline_mode}.json"
    )


def _build_report(
    *,
    scenario: str,
    results: list[StressTaskResult],
    memory: dict[str, object],
    mode: str,
) -> dict[str, object]:
    success_results = [item for item in results if item.status in SUCCESS_STATUSES]
    success_count = len(success_results)
    total_tasks = len(results)
    completion_rate = calculate_completion_rate(total=total_tasks, succeeded=success_count)
    overall_latencies = [item.duration_ms for item in success_results]

    by_engine: dict[str, dict[str, object]] = {}
    for engine in sorted({item.engine for item in results}):
        engine_results = [item for item in results if item.engine == engine]
        engine_success = [item for item in engine_results if item.status in SUCCESS_STATUSES]
        by_engine[engine] = {
            "count": len(engine_results),
            "success_count": len(engine_success),
            "latency_metrics": calculate_latency_metrics(
                [item.duration_ms for item in engine_success]
            ),
        }

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "fixture_profile": FIXTURE_PROFILE,
        "generated_at": _utcnow_iso(),
        "scenario": scenario,
        "base_url": _get_base_url(),
        "mode": mode,
        "concurrency": _get_concurrency(),
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "summary": {
            "total_tasks": total_tasks,
            "success_count": success_count,
            "failure_count": total_tasks - success_count,
            "completion_rate": completion_rate,
            "latency_metrics": calculate_latency_metrics(overall_latencies),
        },
        "by_engine": by_engine,
        "memory": memory,
        "tasks": [asdict(item) for item in results],
    }


def _load_json_report(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return None
    if loaded.get("report_schema_version") != REPORT_SCHEMA_VERSION:
        return None
    if loaded.get("fixture_profile") != FIXTURE_PROFILE:
        return None
    return loaded


def _assert_successful_report(report: dict[str, object], *, expected_tasks: int) -> None:
    summary = cast(dict[str, object], report["summary"])
    assert report["concurrency"] == _get_concurrency()
    assert summary["total_tasks"] == expected_tasks
    assert summary["success_count"] == expected_tasks
    assert cast(float, summary["completion_rate"]) >= 0.95

    task_payloads = cast(list[dict[str, object]], report["tasks"])
    assert len(task_payloads) == expected_tasks
    assert all(_has_non_negative_duration(item) for item in task_payloads)
    assert all(_is_successful_task_payload(item) for item in task_payloads)


def _has_non_negative_duration(item: dict[str, object]) -> bool:
    duration = item.get("duration_ms")
    return isinstance(duration, int | float) and duration >= 0


def _is_successful_task_payload(item: dict[str, object]) -> bool:
    status = item.get("status")
    mode = item.get("mode")
    result_count = item.get("result_count")
    if isinstance(status, str) and status in SUCCESS_STATUSES and mode == "queue":
        return True
    return (
        isinstance(status, str)
        and status in SUCCESS_STATUSES
        and isinstance(result_count, int)
        and result_count >= 1
    )


def _assert_slo_if_enabled(report: dict[str, object]) -> None:
    scenario = report.get("scenario")
    if not isinstance(scenario, str):
        return
    thresholds = SCENARIO_SLO_MS.get(scenario)
    if thresholds is None or os.getenv("ENFORCE_STRESS_SLO", "0") != "1":
        return

    summary = cast(dict[str, object], report["summary"])
    metrics = cast(dict[str, float], summary["latency_metrics"])
    assert metrics["p50_ms"] < thresholds["p50_ms"]
    assert metrics["p95_ms"] < thresholds["p95_ms"]
    assert metrics["p99_ms"] < thresholds["p99_ms"]


def test_parse_memory_mb_supports_docker_units() -> None:
    assert _parse_memory_mb("512MiB") == 512.0
    assert _parse_memory_mb("1.5GiB") == 1536.0
    assert _parse_memory_mb("768kB") == 0.77
    assert _parse_memory_mb("n/a") is None


def test_build_report_tracks_summary_and_engine_breakdown() -> None:
    memory = {
        "available": True,
        "source": "process",
        "sample_count": 1,
        "peak_by_container_mb": {"pytest_process": 128.0},
        "samples": [],
        "error": None,
    }
    results = [
        StressTaskResult(
            scenario="mixed",
            engine="ocr",
            filename="a.pdf",
            content_type="application/pdf",
            mode="serial",
            task_id="task-1",
            status="completed",
            started_at="2026-03-06T00:00:00+00:00",
            completed_at="2026-03-06T00:00:02+00:00",
            duration_ms=2000.0,
            poll_count=2,
            result_count=1,
            download_urls=["/api/tasks/task-1/results/r1/download"],
        ),
        StressTaskResult(
            scenario="mixed",
            engine="text",
            filename="b.txt",
            content_type="text/plain",
            mode="serial",
            task_id="task-2",
            status="completed",
            started_at="2026-03-06T00:00:00+00:00",
            completed_at="2026-03-06T00:00:01+00:00",
            duration_ms=1000.0,
            poll_count=1,
            result_count=1,
            download_urls=["/api/tasks/task-2/results/r2/download"],
        ),
    ]

    report = _build_report(scenario="mixed", results=results, memory=memory, mode="serial")
    summary = cast(dict[str, object], report["summary"])
    latency_metrics = cast(dict[str, float], summary["latency_metrics"])
    by_engine = cast(dict[str, dict[str, object]], report["by_engine"])
    memory_payload = cast(dict[str, object], report["memory"])
    peak_memory = cast(dict[str, float], memory_payload["peak_by_container_mb"])

    assert report["scenario"] == "mixed"
    assert report["mode"] == "serial"
    assert summary["total_tasks"] == 2
    assert summary["success_count"] == 2
    assert summary["completion_rate"] == 1.0
    assert latency_metrics["p95_ms"] >= latency_metrics["p50_ms"]
    assert by_engine["ocr"]["success_count"] == 1
    assert peak_memory["pytest_process"] == 128.0


async def _run_scenario(
    scenario: str,
    specs: list[StressTaskSpec],
    *,
    required_engines: set[str],
) -> dict[str, object]:
    concurrency = _get_concurrency()
    semaphore = asyncio.Semaphore(concurrency)
    mode = _get_mode()

    async with _build_async_client() as client:
        await _ensure_backend_available(client, required_engines=required_engines)
        stop_event = asyncio.Event()
        memory_task = asyncio.create_task(_monitor_memory(stop_event))
        try:
            results = await asyncio.gather(
                *[_run_single_task(client, spec, semaphore) for spec in specs]
            )
        finally:
            stop_event.set()
        memory_summary = await memory_task

    report = _build_report(
        scenario=scenario,
        results=results,
        memory=memory_summary,
        mode=mode,
    )
    report_path = write_json_report(REPORT_DIR, _report_path(scenario, mode).name, report)

    assert report_path == _report_path(scenario, mode)
    return report


@pytest.mark.asyncio
async def test_mixed_engine_concurrent_tasks_report() -> None:
    _require_live_run_enabled()

    specs = _build_mixed_task_specs()
    assert len(specs) == 5

    report = await _run_scenario(
        "mixed",
        specs,
        required_engines={"ocr", "vlm", "text", "markitdown"},
    )

    assert report["mode"] == _get_mode()
    _assert_successful_report(report, expected_tasks=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["ocr", "vlm"])
async def test_single_engine_concurrent_tasks_report(engine: str) -> None:
    _require_live_run_enabled()

    specs = _build_single_engine_specs(engine)
    report = await _run_scenario(
        f"{engine}_only",
        specs,
        required_engines={engine},
    )

    _assert_successful_report(report, expected_tasks=5)
    _assert_slo_if_enabled(report)


@pytest.mark.parametrize("scenario", ["mixed", "ocr_only", "vlm_only"])
def test_serial_queue_comparison_report_available_when_peer_mode_exists(scenario: str) -> None:
    mode = _get_mode()
    current_report = _load_json_report(_report_path(scenario, mode))
    if current_report is None:
        pytest.skip(f"Current mode report not found yet: {_report_path(scenario, mode)}")
    assert current_report is not None

    peer_mode = "queue" if mode == "serial" else "serial"
    peer_report = _load_json_report(_report_path(scenario, peer_mode))
    if peer_report is None:
        pytest.skip(
            f"Run {peer_mode} mode first to compare latency/resource differences for {scenario}."
        )
    assert peer_report is not None

    comparison = build_mode_comparison(
        current_report=current_report,
        baseline_report=peer_report,
    )
    comparison["scenario"] = scenario
    comparison_path = write_json_report(
        REPORT_DIR,
        _comparison_report_path(mode, peer_mode, scenario).name,
        comparison,
    )
    current_report["comparison"] = comparison
    write_json_report(REPORT_DIR, _report_path(scenario, mode).name, current_report)

    assert comparison_path == _comparison_report_path(mode, peer_mode, scenario)
    assert comparison["current_mode"] == mode
    assert comparison["baseline_mode"] == peer_mode

    latency_delta_ms = comparison["latency_delta_ms"]
    assert isinstance(latency_delta_ms, dict)
    assert {"p50_ms", "p95_ms", "p99_ms"}.issubset(latency_delta_ms.keys())

    memory_delta = comparison["memory_peak_delta_mb"]
    assert isinstance(memory_delta, dict)

    summary = current_report.get("summary", {})
    assert isinstance(summary, dict)
    completion_rate = summary.get("completion_rate", 0.0)
    assert isinstance(completion_rate, int | float)
    assert completion_rate >= 0.95
