from __future__ import annotations

import json
import logging
from typing import Any

import redis

from app.config.celery_config import get_celery_settings

logger = logging.getLogger(__name__)
MAX_TRACKED_RUNS = 10


class WorkflowCache:
    """Redis-backed helper for published workflow and task-run tracking metadata."""

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or get_celery_settings().broker_url
        self._redis: Any = redis.Redis.from_url(url, decode_responses=True)

    def get_published(self, dag_hash: str) -> dict[str, Any] | None:
        try:
            return self._load_mapping(self._redis.get(self._published_key(dag_hash)))
        except redis.RedisError as exc:
            logger.debug(
                "Failed to read published workflow cache error_type=%s",
                type(exc).__name__,
            )
            return None

    def set_published(self, dag_hash: str, record: dict[str, Any]) -> None:
        try:
            self._redis.set(self._published_key(dag_hash), json.dumps(record, default=str))
        except redis.RedisError as exc:
            logger.debug(
                "Failed to write published workflow cache error_type=%s",
                type(exc).__name__,
            )

    def get_task_runs(self, workflow_hash: str) -> list[str]:
        entry = self._get_tracking_entry(workflow_hash)
        if entry is None:
            return []
        task_runs = entry.get("task_runs")
        if not isinstance(task_runs, list):
            return []
        return [str(run_id) for run_id in task_runs]

    def get_dag_hash(self, workflow_hash: str) -> str | None:
        entry = self._get_tracking_entry(workflow_hash)
        if entry is None:
            return None
        dag_hash = entry.get("dag_hash")
        return dag_hash if isinstance(dag_hash, str) else None

    def append_task_run(self, workflow_hash: str, dag_hash: str, task_run_id: str) -> None:
        key = self._tracking_key(workflow_hash)
        try:
            pipe = self._redis.pipeline()
            pipe.get(key)
            result = pipe.execute()
            raw = result[0] if result else None

            entry = self._load_mapping(raw) or {"dag_hash": dag_hash, "task_runs": []}
            task_runs = entry.get("task_runs")
            if not isinstance(task_runs, list):
                task_runs = []
            task_runs = [str(run_id) for run_id in task_runs]
            task_runs.append(task_run_id)
            entry = {
                "dag_hash": dag_hash,
                "task_runs": task_runs[-MAX_TRACKED_RUNS:],
            }

            pipe.set(key, json.dumps(entry, default=str))
            pipe.execute()
        except redis.RedisError as exc:
            logger.debug(
                "Failed to append workflow task run cache error_type=%s",
                type(exc).__name__,
            )

    def exists(self, workflow_hash: str) -> bool:
        try:
            return bool(self._redis.exists(self._tracking_key(workflow_hash)))
        except redis.RedisError as exc:
            logger.debug(
                "Failed to check workflow task run cache error_type=%s",
                type(exc).__name__,
            )
            return False

    def warm_tracking(self, workflow_hash: str, dag_hash: str, task_runs: list[str]) -> None:
        entry = {
            "dag_hash": dag_hash,
            "task_runs": [str(run_id) for run_id in task_runs][-MAX_TRACKED_RUNS:],
        }
        try:
            self._redis.set(self._tracking_key(workflow_hash), json.dumps(entry, default=str))
        except redis.RedisError as exc:
            logger.debug(
                "Failed to warm workflow task run cache error_type=%s",
                type(exc).__name__,
            )

    def _get_tracking_entry(self, workflow_hash: str) -> dict[str, Any] | None:
        try:
            return self._load_mapping(self._redis.get(self._tracking_key(workflow_hash)))
        except redis.RedisError as exc:
            logger.debug(
                "Failed to read workflow task run cache error_type=%s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _load_mapping(raw: object) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _published_key(dag_hash: str) -> str:
        return f"wf:pub:{dag_hash}"

    @staticmethod
    def _tracking_key(workflow_hash: str) -> str:
        return f"wf:track:{workflow_hash}"
