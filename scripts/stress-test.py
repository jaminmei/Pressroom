#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import mimetypes
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from re import Pattern
from typing import Any, Sequence

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_SAMPLE_INTERVAL_SECONDS = 5.0

TERMINAL_STATUSES = {"completed", "partial_completed", "failed", "cancelled"}
SUCCESS_TERMINAL_STATUSES = {"completed", "partial_completed"}

SIZE_PATTERN: Pattern[str] = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kmgtp]?i?b)?\s*$",
    re.IGNORECASE,
)
SIZE_MULTIPLIERS: dict[str, int] = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


@dataclass(slots=True)
class TaskSpec:
    engine: str
    file_path: Path
    output_format: str


@dataclass(slots=True)
class TaskResult:
    task_id: str
    engine: str
    status: str
    duration_ms: float
    file_path: str
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in SUCCESS_TERMINAL_STATUSES


@dataclass(slots=True)
class ContainerMemoryStat:
    peak_bytes: float
    limit_bytes: float
    ratio: float


@dataclass(slots=True)
class StressTestReport:
    mode: str
    base_url: str
    concurrency: int
    rounds: int
    total_tasks: int
    completed: int
    failed: int
    completion_rate: float
    latencies_ms: list[float] = field(default_factory=list)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    memory_stats: dict[str, ContainerMemoryStat] = field(default_factory=dict)
    results: list[TaskResult] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _default_fixtures_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "tests" / "fixtures" / "stress"


def build_task_specs(
    rounds: int,
    fixtures_dir: Path,
    *,
    require_existing: bool = True,
) -> list[TaskSpec]:
    scenario = [
        TaskSpec(
            engine="ocr",
            file_path=fixtures_dir / "single-page.pdf",
            output_format="markdown",
        ),
        TaskSpec(
            engine="vlm",
            file_path=fixtures_dir / "single-page.png",
            output_format="markdown",
        ),
        TaskSpec(
            engine="markitdown",
            file_path=fixtures_dir / "multi-page.pdf",
            output_format="markdown",
        ),
        TaskSpec(
            engine="text",
            file_path=fixtures_dir / "sample.txt",
            output_format="plaintext",
        ),
        TaskSpec(
            engine="ocr",
            file_path=fixtures_dir / "single-page.png",
            output_format="plaintext",
        ),
    ]

    if require_existing:
        missing = [str(spec.file_path) for spec in scenario if not spec.file_path.exists()]
        if missing:
            raise FileNotFoundError(
                "Stress test fixture files are missing:\n- " + "\n- ".join(missing)
            )

    tasks: list[TaskSpec] = []
    for _ in range(rounds):
        tasks.extend(scenario)
    return tasks


def _extract_error_message(payload: dict[str, Any]) -> str | None:
    for key in ("error", "message", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


POLL_INTERVAL_SECONDS = 1.0


async def _wait_for_task_terminal_status(
    client: httpx.AsyncClient,
    base_url: str,
    task_id: str,
    timeout_seconds: float,
) -> tuple[str, dict[str, Any], str | None]:
    status_url = f"{base_url.rstrip('/')}/api/tasks/{task_id}"

    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                response = await client.get(status_url, timeout=10.0)
                response.raise_for_status()
                payload = response.json()

                status = str(payload.get("status", "")).strip().lower()
                if status in TERMINAL_STATUSES:
                    error = payload.get("error")
                    failed_message = error if isinstance(error, str) else None
                    return status, payload, failed_message

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except TimeoutError as exc:
        raise TimeoutError(f"Timed out waiting for task {task_id} terminal status") from exc


async def submit_task(
    client: httpx.AsyncClient,
    base_url: str,
    task: TaskSpec,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> TaskResult:
    started = time.perf_counter()
    task_id = "unknown"

    try:
        task_create_url = f"{base_url.rstrip('/')}/api/tasks"
        content_type = mimetypes.guess_type(task.file_path.name)[0] or "application/octet-stream"

        with task.file_path.open("rb") as upload_stream:
            response = await client.post(
                task_create_url,
                data={"engine": task.engine, "output_format": task.output_format},
                files={"file": (task.file_path.name, upload_stream, content_type)},
                timeout=min(timeout_seconds, 30.0),
            )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("POST /api/tasks returned non-object JSON payload")

        raw_task_id = payload.get("task_id")
        if not isinstance(raw_task_id, str) or not raw_task_id:
            raise ValueError("POST /api/tasks response missing task_id")
        task_id = raw_task_id

        elapsed_seconds = time.perf_counter() - started
        remaining_timeout = timeout_seconds - elapsed_seconds
        if remaining_timeout <= 0:
            raise TimeoutError(f"Task {task_id} timed out before polling started")

        (
            terminal_status,
            terminal_payload,
            task_failed_message,
        ) = await _wait_for_task_terminal_status(
            client,
            base_url,
            task_id,
            remaining_timeout,
        )

        total_duration_ms = (time.perf_counter() - started) * 1000
        if terminal_status in SUCCESS_TERMINAL_STATUSES:
            return TaskResult(
                task_id=task_id,
                engine=task.engine,
                status=terminal_status,
                duration_ms=total_duration_ms,
                file_path=str(task.file_path),
            )

        error_message = (
            task_failed_message
            or _extract_error_message(terminal_payload)
            or f"Terminal status: {terminal_status}"
        )
        return TaskResult(
            task_id=task_id,
            engine=task.engine,
            status=terminal_status,
            duration_ms=total_duration_ms,
            file_path=str(task.file_path),
            error=error_message,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        return TaskResult(
            task_id=task_id,
            engine=task.engine,
            status="timeout",
            duration_ms=(time.perf_counter() - started) * 1000,
            file_path=str(task.file_path),
            error=str(exc),
        )
    except (httpx.HTTPError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return TaskResult(
            task_id=task_id,
            engine=task.engine,
            status="failed",
            duration_ms=(time.perf_counter() - started) * 1000,
            file_path=str(task.file_path),
            error=str(exc),
        )


async def run_concurrent_tasks(
    client: httpx.AsyncClient,
    base_url: str,
    tasks: Sequence[TaskSpec],
    concurrency: int,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[TaskResult]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded_submit(task: TaskSpec) -> TaskResult:
        async with semaphore:
            try:
                return await submit_task(
                    client,
                    base_url,
                    task,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                return TaskResult(
                    task_id="unknown",
                    engine=task.engine,
                    status="failed",
                    duration_ms=0.0,
                    file_path=str(task.file_path),
                    error=f"Unhandled exception: {exc}",
                )

    return await asyncio.gather(*[_bounded_submit(task) for task in tasks])


def _parse_size_to_bytes(raw_value: str) -> float:
    normalized = raw_value.strip().replace(",", "")
    if not normalized:
        return 0.0
    if normalized == "0" or normalized.lower() == "0b":
        return 0.0

    matched = SIZE_PATTERN.match(normalized)
    if matched is None:
        return 0.0

    value = float(matched.group("value"))
    unit = (matched.group("unit") or "b").lower()
    return value * SIZE_MULTIPLIERS.get(unit, 1)


def _parse_mem_usage_pair(mem_usage: str) -> tuple[float, float]:
    if "/" not in mem_usage:
        return 0.0, 0.0
    current_raw, limit_raw = mem_usage.split("/", 1)
    return _parse_size_to_bytes(current_raw), _parse_size_to_bytes(limit_raw)


async def _docker_stats_snapshot() -> list[dict[str, str]]:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "docker stats command failed")

    output = stdout.decode("utf-8", errors="replace")
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            rows.append({str(key): str(value) for key, value in decoded.items()})
    return rows


async def collect_memory_stats(
    stop_event: asyncio.Event,
    *,
    sample_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
) -> dict[str, ContainerMemoryStat]:
    peak_usage: dict[str, float] = {}
    memory_limits: dict[str, float] = {}

    interval = max(0.1, sample_interval_seconds)
    while True:
        try:
            snapshot = await _docker_stats_snapshot()
        except Exception:  # noqa: BLE001 - best effort monitor, should not block stress tasks.
            snapshot = []

        for row in snapshot:
            name = row.get("Name", "").strip()
            mem_usage = row.get("MemUsage", "")
            if not name:
                continue

            usage_bytes, limit_bytes = _parse_mem_usage_pair(mem_usage)
            if usage_bytes <= 0 and limit_bytes <= 0:
                continue

            peak_usage[name] = max(peak_usage.get(name, 0.0), usage_bytes)
            if limit_bytes > 0:
                memory_limits[name] = max(memory_limits.get(name, 0.0), limit_bytes)

        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    memory_stats: dict[str, ContainerMemoryStat] = {}
    for name in sorted(peak_usage):
        peak = peak_usage[name]
        limit = memory_limits.get(name, 0.0)
        ratio = peak / limit if limit > 0 else 0.0
        memory_stats[name] = ContainerMemoryStat(peak_bytes=peak, limit_bytes=limit, ratio=ratio)
    return memory_stats


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(len(sorted_values) * percentile))
    return float(sorted_values[min(rank - 1, len(sorted_values) - 1)])


def calculate_percentiles(latencies: Sequence[float]) -> tuple[float, float, float]:
    if not latencies:
        return 0.0, 0.0, 0.0
    sorted_values = sorted(float(value) for value in latencies)
    return (
        _percentile(sorted_values, 0.50),
        _percentile(sorted_values, 0.95),
        _percentile(sorted_values, 0.99),
    )


def _format_mib(value_in_bytes: float) -> str:
    return f"{value_in_bytes / (1024**2):.2f}"


def _format_ratio(ratio: float) -> str:
    if ratio <= 0:
        return "N/A"
    return f"{ratio:.2%}"


def generate_report(report: StressTestReport) -> str:
    lines = [
        "# Stress Test Report",
        "",
        f"- Generated At (UTC): {report.generated_at.isoformat()}",
        f"- Base URL: `{report.base_url}`",
        f"- Mode: `{report.mode}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Concurrency | {report.concurrency} |",
        f"| Rounds | {report.rounds} |",
        f"| Total Tasks | {report.total_tasks} |",
        f"| Completed | {report.completed} |",
        f"| Failed | {report.failed} |",
        f"| Completion Rate | {report.completion_rate:.2%} |",
        "",
        "## Latency Percentiles (ms)",
        "",
        "| p50 | p95 | p99 |",
        "|-----|-----|-----|",
        f"| {report.p50_ms:.2f} | {report.p95_ms:.2f} | {report.p99_ms:.2f} |",
        "",
        "## Memory Peak",
        "",
        "| Container | Peak Memory (MiB) | Memory Limit (MiB) | Ratio (Peak/Limit) |",
        "|-----------|-------------------|--------------------|--------------------|",
    ]

    if report.memory_stats:
        for name, stat in sorted(report.memory_stats.items()):
            limit_text = _format_mib(stat.limit_bytes) if stat.limit_bytes > 0 else "N/A"
            lines.append(
                f"| {name} | {_format_mib(stat.peak_bytes)} | "
                f"{limit_text} | {_format_ratio(stat.ratio)} |"
            )
    else:
        lines.append("| (no data) | 0.00 | N/A | N/A |")

    failure_items = [item for item in report.results if not item.succeeded]
    if failure_items:
        lines.extend(
            [
                "",
                "## Failures",
                "",
                "| Task ID | Engine | Status | Error |",
                "|---------|--------|--------|-------|",
            ]
        )
        for result in failure_items:
            error_text = (result.error or "").replace("\n", " ").strip() or "-"
            lines.append(f"| {result.task_id} | {result.engine} | {result.status} | {error_text} |")

    lines.append("")
    return "\n".join(lines)


def build_report(
    *,
    mode: str,
    base_url: str,
    concurrency: int,
    rounds: int,
    results: list[TaskResult],
    memory_stats: dict[str, ContainerMemoryStat],
) -> StressTestReport:
    total_tasks = len(results)
    completed = sum(1 for result in results if result.succeeded)
    failed = total_tasks - completed
    completion_rate = completed / total_tasks if total_tasks else 0.0

    latency_samples = [result.duration_ms for result in results if result.succeeded]
    p50_ms, p95_ms, p99_ms = calculate_percentiles(latency_samples)

    return StressTestReport(
        mode=mode,
        base_url=base_url,
        concurrency=concurrency,
        rounds=rounds,
        total_tasks=total_tasks,
        completed=completed,
        failed=failed,
        completion_rate=completion_rate,
        latencies_ms=latency_samples,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        memory_stats=memory_stats,
        results=results,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="stress benchmark script")
    parser.add_argument("--mode", choices=("serial", "queue"), default="serial")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("docs/stress-test-report.md"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )
    parser.add_argument("--fixtures-dir", type=Path, default=_default_fixtures_dir())

    args = parser.parse_args(argv)
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be > 0")
    if args.sample_interval_seconds <= 0:
        parser.error("--sample-interval-seconds must be > 0")
    return args


async def run_stress_test(args: argparse.Namespace) -> StressTestReport | None:
    tasks = build_task_specs(
        rounds=args.rounds,
        fixtures_dir=args.fixtures_dir,
        require_existing=not args.dry_run,
    )

    print(
        "Starting stress test: "
        f"mode={args.mode}, concurrency={args.concurrency}, rounds={args.rounds}, "
        f"base_url={args.base_url}"
    )

    if args.dry_run:
        print(f"Dry run: planned {len(tasks)} tasks from fixtures at {args.fixtures_dir}")
        preview_count = min(5, len(tasks))
        for index in range(preview_count):
            task = tasks[index]
            print(
                f"  #{index + 1}: engine={task.engine}, "
                f"output={task.output_format}, file={task.file_path}"
            )
        if len(tasks) > preview_count:
            print(f"  ... and {len(tasks) - preview_count} more tasks")
        return None

    stop_event = asyncio.Event()
    memory_collector = asyncio.create_task(
        collect_memory_stats(
            stop_event,
            sample_interval_seconds=args.sample_interval_seconds,
        )
    )

    results: list[TaskResult] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            results = await run_concurrent_tasks(
                client,
                args.base_url,
                tasks,
                args.concurrency,
                timeout_seconds=args.timeout_seconds,
            )
    finally:
        stop_event.set()

    memory_stats = await memory_collector
    report = build_report(
        mode=args.mode,
        base_url=args.base_url,
        concurrency=args.concurrency,
        rounds=args.rounds,
        results=results,
        memory_stats=memory_stats,
    )
    markdown = generate_report(report)

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Report generated at: {output_path}")
    print(
        f"Completion: {report.completed}/{report.total_tasks} ({report.completion_rate:.2%}), "
        f"p95={report.p95_ms:.2f}ms, p99={report.p99_ms:.2f}ms"
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run_stress_test(args))
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("Interrupted")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
