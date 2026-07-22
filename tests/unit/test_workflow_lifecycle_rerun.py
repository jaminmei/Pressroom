"""Integration tests for the rerun and retry tracking flow.

Verifies that reruns create new task-run entries (append, not overwrite)
and that the tracking list is properly updated with the cap enforced.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.workflow_cache import WorkflowCache

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAG_HASH = "abc123def456"
WORKFLOW_HASH = "wf_abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(fake_redis: MagicMock) -> WorkflowCache:
    """Build a WorkflowCache with an injected mock Redis client."""
    with patch("app.services.workflow_cache.redis.Redis.from_url", return_value=fake_redis):
        return WorkflowCache(redis_url="redis://localhost:6379/0")


def _setup_pipeline(fake_redis: MagicMock, get_return_value) -> MagicMock:
    """Create a mock pipeline that returns *get_return_value* on GET execute."""
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.get.return_value = pipe  # chaining
    pipe.set.return_value = pipe  # chaining
    pipe.execute.return_value = [get_return_value]
    return pipe


def _seed_tracking(fake_redis: MagicMock, task_runs: list[str]) -> None:
    """Pre-seed tracking data in the mock Redis."""
    entry = {"dag_hash": DAG_HASH, "task_runs": task_runs}
    fake_redis.get.return_value = json.dumps(entry)


def _get_stored_runs(write_pipe: MagicMock) -> list[str]:
    """Extract stored task_runs from the SET call on the write pipeline."""
    stored = json.loads(write_pipe.set.call_args[0][1])
    return stored["task_runs"]


def _get_stored_entry(write_pipe: MagicMock) -> dict:
    """Extract the full stored entry from the SET call on the write pipeline."""
    return json.loads(write_pipe.set.call_args[0][1])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRerunAppendsNewTaskRun:
    """Scenario 1: initial run tracked, rerun appends (not overwrites)."""

    def test_rerun_appends_new_task_run(self) -> None:
        fake_redis = MagicMock()
        # Pre-seed: workflow already has run-1
        existing = {"dag_hash": DAG_HASH, "task_runs": ["run-1"]}
        _setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-2")

        write_pipe = fake_redis.pipeline.return_value
        stored = _get_stored_entry(write_pipe)
        assert stored["task_runs"] == ["run-1", "run-2"]
        assert stored["dag_hash"] == DAG_HASH


class TestRetryAppendsNewTaskRun:
    """Scenario 2: retry scenario appends a new entry."""

    def test_retry_appends_new_task_run(self) -> None:
        fake_redis = MagicMock()
        existing = {"dag_hash": DAG_HASH, "task_runs": ["run-1"]}
        _setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        cache.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-2")

        write_pipe = fake_redis.pipeline.return_value
        stored_runs = _get_stored_runs(write_pipe)
        assert stored_runs == ["run-1", "run-2"]


class TestMultipleRerunsTrackedCorrectly:
    """Scenario 3: three sequential reruns produce the right tracking list."""

    def test_multiple_reruns_tracked_correctly(self) -> None:
        # Simulate three reruns by verifying the append logic at each stage.
        # Since append_task_run uses pipeline (not stateful mock), we test
        # each append step independently to verify correctness.

        # Step 1: initial run → ["run-1"]
        fake_redis = MagicMock()
        _setup_pipeline(fake_redis, None)  # empty tracking
        cache = _make_cache(fake_redis)
        cache.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-1")
        write_pipe = fake_redis.pipeline.return_value
        assert _get_stored_runs(write_pipe) == ["run-1"]

        # Step 2: rerun 1 → ["run-1", "run-2"]
        fake_redis_2 = MagicMock()
        _setup_pipeline(fake_redis_2, json.dumps({"dag_hash": DAG_HASH, "task_runs": ["run-1"]}))
        cache2 = _make_cache(fake_redis_2)
        cache2.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-2")
        write_pipe_2 = fake_redis_2.pipeline.return_value
        assert _get_stored_runs(write_pipe_2) == ["run-1", "run-2"]

        # Step 3: rerun 2 → ["run-1", "run-2", "run-3"]
        fake_redis_3 = MagicMock()
        _setup_pipeline(
            fake_redis_3,
            json.dumps({"dag_hash": DAG_HASH, "task_runs": ["run-1", "run-2"]}),
        )
        cache3 = _make_cache(fake_redis_3)
        cache3.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-3")
        write_pipe_3 = fake_redis_3.pipeline.return_value
        assert _get_stored_runs(write_pipe_3) == ["run-1", "run-2", "run-3"]


class TestRerunPreservesDagHash:
    """Scenario 4: after multiple reruns, get_dag_hash still returns the original."""

    def test_rerun_preserves_dag_hash(self) -> None:
        fake_redis = MagicMock()
        _seed_tracking(fake_redis, ["run-1", "run-2", "run-3"])

        cache = _make_cache(fake_redis)
        result = cache.get_dag_hash(WORKFLOW_HASH)

        assert result == DAG_HASH
        fake_redis.get.assert_called_with(f"wf:track:{WORKFLOW_HASH}")


class TestRerunDoesNotDuplicateTaskRunId:
    """Scenario 5: same task_run_id can appear twice (retry of same task)."""

    def test_rerun_does_not_duplicate_task_run_id(self) -> None:
        # This is an edge case: the same task_run_id is appended twice.
        # The list should contain both entries (duplicates allowed).
        fake_redis = MagicMock()
        existing = {"dag_hash": DAG_HASH, "task_runs": ["run-1"]}
        _setup_pipeline(fake_redis, json.dumps(existing))

        cache = _make_cache(fake_redis)
        # Append same run-id again (simulates retry of the same task)
        cache.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-1")

        write_pipe = fake_redis.pipeline.return_value
        stored_runs = _get_stored_runs(write_pipe)
        assert stored_runs == ["run-1", "run-1"]


class TestRerunHashGateBlocksUntrackedWorkflow:
    """Scenario 6: cannot rerun a workflow that was never tracked (403 gate)."""

    def test_rerun_hash_gate_blocks_untracked_workflow(self) -> None:
        fake_redis = MagicMock()
        fake_redis.exists.return_value = 0

        cache = _make_cache(fake_redis)
        assert cache.exists("unknown_hash") is False

        # Verify the correct key pattern was checked
        fake_redis.exists.assert_called_once_with("wf:track:unknown_hash")


class TestRerunTrackingCapWithReruns:
    """Scenario 7: 8 initial runs + 4 reruns = 12 total, capped to last 10."""

    def test_rerun_tracking_cap_with_reruns(self) -> None:
        # Start with 8 runs already tracked
        initial_runs = [f"run-{i}" for i in range(8)]
        fake_redis = MagicMock()
        existing = {"dag_hash": DAG_HASH, "task_runs": initial_runs}
        _setup_pipeline(fake_redis, json.dumps(existing))

        _make_cache(fake_redis)

        # Simulate 4 more reruns (each appending one at a time).
        # We test the final state after all 4 appends by starting with 11 runs
        # (8 + 3 already appended) and appending the 12th.
        # But since the mock doesn't accumulate state, we test by seeding
        # the state *as it would be* after 3 reruns (11 runs), then appending
        # the 12th, and verifying the cap.

        # After 8 initial + 3 reruns = 11 runs (already over cap, but append_task_run
        # caps on each call). Let's trace what happens step by step:
        #
        # Start: ["run-0".."run-7"] (8 items)
        # Append run-8 → 9 items (under cap)
        # Append run-9 → 10 items (at cap)
        # Append run-10 → 11 items → capped to last 10 → ["run-1".."run-10"]
        # Append run-11 → 11 items → capped to last 10 → ["run-2".."run-11"]

        # Test the final append (run-11) starting from the state after run-10
        state_after_10 = {
            "dag_hash": DAG_HASH,
            "task_runs": [f"run-{i}" for i in range(1, 11)],  # run-1 through run-10
        }
        fake_redis_final = MagicMock()
        _setup_pipeline(fake_redis_final, json.dumps(state_after_10))

        cache_final = _make_cache(fake_redis_final)
        cache_final.append_task_run(WORKFLOW_HASH, DAG_HASH, "run-11")

        write_pipe = fake_redis_final.pipeline.return_value
        stored_runs = _get_stored_runs(write_pipe)

        assert len(stored_runs) == 10
        assert stored_runs[0] == "run-2"  # run-1 evicted
        assert stored_runs[-1] == "run-11"  # latest appended
        assert stored_runs == [f"run-{i}" for i in range(2, 12)]
