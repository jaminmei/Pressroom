from __future__ import annotations

import os
import select
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from app.config.celery_config import CelerySettings
from app.worker import create_celery_app
from app.worker_tasks import WORKER_SMOKE_TASK_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]
START_WORKER_SCRIPT = REPO_ROOT / "scripts" / "start_worker.sh"


def _is_redis_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _drain_worker_logs(process: subprocess.Popen[str], logs: list[str], *, timeout: float) -> None:
    if process.stdout is None:
        return

    end_time = time.time() + timeout
    while time.time() < end_time:
        remaining = max(end_time - time.time(), 0.05)
        readable, _, _ = select.select([process.stdout], [], [], min(remaining, 0.2))
        if not readable:
            continue

        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                return
            continue
        logs.append(line.strip())


def _wait_for_worker_ready(process: subprocess.Popen[str], logs: list[str]) -> None:
    deadline = time.time() + 30.0
    saw_redis_connect = False
    saw_ready = False

    while time.time() < deadline:
        _drain_worker_logs(process, logs, timeout=0.5)

        if process.poll() is not None:
            joined_logs = "\n".join(logs[-80:])
            raise AssertionError(f"Worker exited unexpectedly.\n{joined_logs}")

        lower_logs = [line.lower() for line in logs]
        saw_redis_connect = saw_redis_connect or any(
            "connected to redis://" in line for line in lower_logs
        )
        saw_ready = saw_ready or any("ready." in line for line in lower_logs)
        if saw_redis_connect and saw_ready:
            return

    joined_logs = "\n".join(logs[-120:])
    raise AssertionError(f"Worker did not become ready in time.\n{joined_logs}")


def _wait_for_task_log(
    process: subprocess.Popen[str],
    logs: list[str],
    expected_fragment: str,
) -> None:
    deadline = time.time() + 20.0
    fragment = expected_fragment.lower()
    while time.time() < deadline:
        _drain_worker_logs(process, logs, timeout=0.5)
        if any(fragment in line.lower() for line in logs):
            return
        if process.poll() is not None:
            break
    joined_logs = "\n".join(logs[-120:])
    raise AssertionError(f"Expected log fragment not found: {expected_fragment}\n{joined_logs}")


def _stop_process(process: subprocess.Popen[str], logs: list[str]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    finally:
        _drain_worker_logs(process, logs, timeout=0.5)


def test_start_worker_script_starts_worker_and_processes_task() -> None:
    if not _is_redis_reachable():
        pytest.skip(
            "Redis is not reachable on localhost:6379. Run docker compose --profile full up -d."
        )

    env = os.environ.copy()
    redis_password = env.get("REDIS_PASSWORD")
    if not redis_password:
        pytest.skip("REDIS_PASSWORD is required for the authenticated Redis smoke test")
    env["CELERY_BROKER_URL"] = f"redis://:{redis_password}@localhost:6379/0"
    env["CELERY_RESULT_BACKEND"] = f"redis://:{redis_password}@localhost:6379/1"
    env["CELERY_WORKER_POOL"] = "solo"
    env["CELERY_WORKER_CONCURRENCY"] = "1"
    env["CELERY_WORKER_LOGLEVEL"] = "info"
    queue_name = f"worker-smoke-{uuid.uuid4().hex[:8]}"
    env["CELERY_WORKER_QUEUES"] = queue_name

    process = subprocess.Popen(
        ["bash", str(START_WORKER_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    logs: list[str] = []

    try:
        _wait_for_worker_ready(process, logs)

        celery_app = create_celery_app(
            CelerySettings(
                celery_broker_url=env["CELERY_BROKER_URL"],
                celery_result_backend=env["CELERY_RESULT_BACKEND"],
            )
        )
        payload = f"smoke-{uuid.uuid4()}"
        result = celery_app.send_task(
            WORKER_SMOKE_TASK_NAME,
            args=[payload],
            queue=queue_name,
        ).get(timeout=20)

        assert result == {"echo": payload}
        _wait_for_task_log(process, logs, f"Task {WORKER_SMOKE_TASK_NAME}")
        _wait_for_task_log(process, logs, "received")
    finally:
        _stop_process(process, logs)
