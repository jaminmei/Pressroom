from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "stress-test.py"


@pytest.fixture(scope="module")
def stress_module() -> ModuleType:
    if not SCRIPT_PATH.exists():
        pytest.skip("scripts/stress-test.py not found")

    spec = importlib.util.spec_from_file_location("stress_test_script", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_calculate_percentiles_empty(stress_module: ModuleType) -> None:
    assert stress_module.calculate_percentiles([]) == (0.0, 0.0, 0.0)


def test_calculate_percentiles_single_value(stress_module: ModuleType) -> None:
    assert stress_module.calculate_percentiles([123.45]) == pytest.approx((123.45, 123.45, 123.45))


def test_calculate_percentiles_multiple_values(stress_module: ModuleType) -> None:
    p50, p95, p99 = stress_module.calculate_percentiles([10.0, 20.0, 30.0, 40.0, 50.0])
    assert p50 == pytest.approx(30.0)
    assert p95 == pytest.approx(50.0)
    assert p99 == pytest.approx(50.0)


def test_parse_memory_helpers(stress_module: ModuleType) -> None:
    parse_size = stress_module._parse_size_to_bytes  # noqa: SLF001
    parse_pair = stress_module._parse_mem_usage_pair  # noqa: SLF001

    assert parse_size("512MiB") == pytest.approx(512 * 1024 * 1024)
    assert parse_size("1GiB") == pytest.approx(1024 * 1024 * 1024)

    used, limit = parse_pair("512MiB / 1GiB")
    assert used == pytest.approx(512 * 1024 * 1024)
    assert limit == pytest.approx(1024 * 1024 * 1024)


def test_generate_report_contains_key_fields(stress_module: ModuleType) -> None:
    container_stat_cls = stress_module.ContainerMemoryStat
    task_result_cls = stress_module.TaskResult
    report_cls = stress_module.StressTestReport

    report = report_cls(
        mode="serial",
        base_url="http://localhost:8000",
        concurrency=5,
        rounds=1,
        total_tasks=5,
        completed=4,
        failed=1,
        completion_rate=0.8,
        latencies_ms=[100.0, 200.0, 300.0, 400.0],
        p50_ms=250.0,
        p95_ms=400.0,
        p99_ms=400.0,
        memory_stats={
            "backend": container_stat_cls(
                peak_bytes=512 * 1024 * 1024,
                limit_bytes=1024 * 1024 * 1024,
                ratio=0.5,
            )
        },
        results=[
            task_result_cls(
                task_id="task-1",
                engine="ocr",
                status="failed",
                duration_ms=1000.0,
                file_path="tests/fixtures/stress/single-page.pdf",
                error="forced failure",
            )
        ],
        generated_at=datetime.now(timezone.utc),
    )

    markdown = stress_module.generate_report(report)
    normalized = markdown.lower()
    for token in ("mode", "concurrency", "completed", "failed", "p50", "p95", "p99"):
        assert token in normalized
    assert "completion rate" in normalized
    assert "backend" in markdown
    assert "forced failure" in markdown


def test_parse_args_supports_required_flags(stress_module: ModuleType) -> None:
    args = stress_module.parse_args(
        [
            "--mode",
            "queue",
            "--concurrency",
            "7",
            "--rounds",
            "11",
            "--output",
            "docs/custom-stress.md",
            "--dry-run",
        ]
    )

    assert args.mode == "queue"
    assert args.concurrency == 7
    assert args.rounds == 11
    assert str(args.output).endswith("custom-stress.md")
    assert args.dry_run is True
