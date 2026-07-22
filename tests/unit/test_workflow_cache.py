from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import redis

from app.services.workflow_cache import WorkflowCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(fake_redis: MagicMock) -> WorkflowCache:
    """Build a WorkflowCache with an injected mock Redis client.

    Uses the constructor's redis_url path to avoid CelerySettings dependency.
    """
    with patch("app.services.workflow_cache.redis.Redis.from_url", return_value=fake_redis):
        cache = WorkflowCache(redis_url="redis://localhost:6379/0")
    return cache


# ---------------------------------------------------------------------------
# get_published
# ---------------------------------------------------------------------------


class TestGetPublished:
    def test_returns_parsed_data_on_hit(self) -> None:
        fake_redis = MagicMock()
        record = {"dag_hash": "abc123", "status": "published"}
        fake_redis.get.return_value = json.dumps(record)

        cache = _make_cache(fake_redis)
        result = cache.get_published("abc123")

        assert result == record
        fake_redis.get.assert_called_once_with("wf:pub:abc123")

    def test_returns_none_on_miss(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.return_value = None

        cache = _make_cache(fake_redis)
        assert cache.get_published("missing") is None

    def test_returns_none_on_redis_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.side_effect = redis.RedisError("connection refused")

        cache = _make_cache(fake_redis)
        assert cache.get_published("abc123") is None

    def test_returns_none_on_json_decode_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.return_value = "not-valid-json{{{"

        cache = _make_cache(fake_redis)
        assert cache.get_published("abc123") is None


# ---------------------------------------------------------------------------
# set_published
# ---------------------------------------------------------------------------


class TestSetPublished:
    def test_stores_json(self) -> None:
        fake_redis = MagicMock()
        cache = _make_cache(fake_redis)

        record = {"dag_hash": "abc", "nodes": 5}
        cache.set_published("abc", record)

        fake_redis.set.assert_called_once_with("wf:pub:abc", json.dumps(record, default=str))

    def test_swallows_redis_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.set.side_effect = redis.RedisError("write failed")

        cache = _make_cache(fake_redis)
        # Should not raise
        cache.set_published("abc", {"dag_hash": "abc"})


# ---------------------------------------------------------------------------
# get_task_runs
# ---------------------------------------------------------------------------


class TestGetTaskRuns:
    def test_returns_run_list_on_hit(self) -> None:
        fake_redis = MagicMock()
        entry = {"dag_hash": "d1", "task_runs": ["run-1", "run-2"]}
        fake_redis.get.return_value = json.dumps(entry)

        cache = _make_cache(fake_redis)
        assert cache.get_task_runs("w1") == ["run-1", "run-2"]

    def test_returns_empty_list_on_miss(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.return_value = None

        cache = _make_cache(fake_redis)
        assert cache.get_task_runs("w1") == []


# ---------------------------------------------------------------------------
# get_dag_hash
# ---------------------------------------------------------------------------


class TestGetDagHash:
    def test_returns_dag_hash_on_hit(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps({"dag_hash": "dag-abc", "task_runs": []})

        cache = _make_cache(fake_redis)
        assert cache.get_dag_hash("w1") == "dag-abc"

    def test_returns_none_on_miss(self) -> None:
        fake_redis = MagicMock()
        fake_redis.get.return_value = None

        cache = _make_cache(fake_redis)
        assert cache.get_dag_hash("w1") is None


# ---------------------------------------------------------------------------
# append_task_run
# ---------------------------------------------------------------------------


class TestAppendTaskRun:
    @staticmethod
    def _setup_pipeline(fake_redis: MagicMock, get_return_value) -> MagicMock:
        """Create a mock pipeline that returns *get_return_value* on GET."""
        pipe = MagicMock()
        fake_redis.pipeline.return_value = pipe
        pipe.get.return_value = pipe  # chaining
        pipe.set.return_value = pipe  # chaining
        pipe.execute.return_value = [get_return_value]
        return pipe

    def test_appends_to_existing_entry(self) -> None:
        fake_redis = MagicMock()
        existing = {"dag_hash": "dag1", "task_runs": ["run-1"]}
        self._setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run("w1", "dag1", "run-2")

        # The write pipeline — inspect the SET call on the shared pipe mock
        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["task_runs"] == ["run-1", "run-2"]

    def test_creates_entry_when_missing(self) -> None:
        fake_redis = MagicMock()
        self._setup_pipeline(fake_redis, None)

        cache = _make_cache(fake_redis)
        cache.append_task_run("w1", "dag1", "run-1")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["task_runs"] == ["run-1"]
        assert stored["dag_hash"] == "dag1"

    def test_caps_at_10_entries(self) -> None:
        fake_redis = MagicMock()
        existing_runs = [f"run-{i}" for i in range(9)]
        existing = {"dag_hash": "dag1", "task_runs": existing_runs}
        self._setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run("w1", "dag1", "run-10")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert len(stored["task_runs"]) == 10
        assert stored["task_runs"][-1] == "run-10"

    def test_caps_and_discards_oldest_when_over_10(self) -> None:
        fake_redis = MagicMock()
        existing_runs = [f"run-{i}" for i in range(10)]
        existing = {"dag_hash": "dag1", "task_runs": existing_runs}
        self._setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run("w1", "dag1", "run-11")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert len(stored["task_runs"]) == 10
        assert stored["task_runs"][0] == "run-1"  # "run-0" was evicted
        assert stored["task_runs"][-1] == "run-11"

    def test_swallows_redis_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.pipeline.side_effect = redis.RedisError("down")

        cache = _make_cache(fake_redis)
        # Should not raise
        cache.append_task_run("w1", "dag1", "run-1")

    def test_uses_pipeline_for_atomic_read_write(self) -> None:
        """Verify append_task_run uses Redis pipeline (not bare get/set)."""
        fake_redis = MagicMock()
        existing = {"dag_hash": "dag1", "task_runs": ["run-1"]}
        self._setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run("w1", "dag1", "run-2")

        # pipeline() must have been called (at least once for the read phase)
        assert fake_redis.pipeline.called, "append_task_run should use pipeline()"
        # Direct get/set must NOT have been called on the redis client itself
        assert not fake_redis.get.called, "append_task_run must not call redis.get() directly"
        assert not fake_redis.set.called, "append_task_run must not call redis.set() directly"


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    def test_returns_true_when_key_exists(self) -> None:
        fake_redis = MagicMock()
        fake_redis.exists.return_value = 1

        cache = _make_cache(fake_redis)
        assert cache.exists("w1") is True
        fake_redis.exists.assert_called_once_with("wf:track:w1")

    def test_returns_false_when_key_missing(self) -> None:
        fake_redis = MagicMock()
        fake_redis.exists.return_value = 0

        cache = _make_cache(fake_redis)
        assert cache.exists("missing") is False

    def test_returns_false_on_redis_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.exists.side_effect = redis.RedisError("unavailable")

        cache = _make_cache(fake_redis)
        assert cache.exists("w1") is False


# ---------------------------------------------------------------------------
# warm_tracking
# ---------------------------------------------------------------------------


class TestWarmTracking:
    def test_stores_capped_run_list(self) -> None:
        fake_redis = MagicMock()
        cache = _make_cache(fake_redis)

        runs = [f"run-{i}" for i in range(15)]
        cache.warm_tracking("w1", "dag1", runs)

        stored = json.loads(fake_redis.set.call_args[0][1])
        assert len(stored["task_runs"]) == 10
        assert stored["task_runs"][0] == "run-5"  # last 10 of 15
        assert stored["dag_hash"] == "dag1"

    def test_swallows_redis_error(self) -> None:
        fake_redis = MagicMock()
        fake_redis.set.side_effect = redis.RedisError("down")

        cache = _make_cache(fake_redis)
        # Should not raise
        cache.warm_tracking("w1", "dag1", ["run-1"])


# ---------------------------------------------------------------------------
# Constructor injection
# ---------------------------------------------------------------------------


class TestConstructorInjection:
    def test_redis_url_creates_client_from_url(self) -> None:
        fake_redis = MagicMock()
        with patch(
            "app.services.workflow_cache.redis.Redis.from_url", return_value=fake_redis
        ) as mock_from_url:
            cache = WorkflowCache(redis_url="redis://custom:6379/1")

        mock_from_url.assert_called_once_with("redis://custom:6379/1", decode_responses=True)
        assert cache._redis is fake_redis

    def test_no_redis_url_falls_back_to_celery_settings(self) -> None:
        fake_redis = MagicMock()
        with patch(
            "app.services.workflow_cache.redis.Redis.from_url", return_value=fake_redis
        ) as mock_from_url:
            cache = WorkflowCache()

        # Should have been called with whatever CelerySettings provides
        assert mock_from_url.called
        assert cache._redis is fake_redis
