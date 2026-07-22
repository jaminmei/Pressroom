"""Integration tests for the publish -> duplicate detection -> task run tracking flow.

These tests exercise the full lifecycle using mock Redis so no real infrastructure
is needed.  They verify that:

1. compute_dag_hash produces deterministic hashes for identical topology.
2. WorkflowCache correctly detects new vs duplicate published workflows.
3. Task run tracking (append / cap / exists) works end-to-end.
4. The combined publish-then-run flow integrates correctly.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.workflow_cache import WorkflowCache
from app.utils.workflow_hash import compute_dag_hash, compute_workflow_hash

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(fake_redis: MagicMock) -> WorkflowCache:
    """Build a WorkflowCache with an injected mock Redis client."""
    with patch("app.services.workflow_cache.redis.Redis.from_url", return_value=fake_redis):
        return WorkflowCache(redis_url="redis://localhost:6379/0")


def _setup_pipeline(fake_redis: MagicMock, get_return_value) -> MagicMock:
    """Create a mock pipeline that returns *get_return_value* on the first execute."""
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.get.return_value = pipe
    pipe.set.return_value = pipe
    pipe.execute.return_value = [get_return_value]
    return pipe


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

NODES = [
    {"id": "n1", "type": "input/image"},
    {"id": "n2", "type": "engine/ocr"},
    {"id": "n3", "type": "end/final"},
]

EDGES = [
    {"source": "n1", "target": "n2"},
    {"source": "n2", "target": "n3"},
]

NODE_CONFIGS = {
    "n1": {},
    "n2": {"model": "rapidocr"},
    "n3": {},
}

INPUT_FILES = [
    {"name": "test.pdf", "size": 1024},
]


# ---------------------------------------------------------------------------
# Test: publish new workflow
# ---------------------------------------------------------------------------


class TestPublishNewWorkflow:
    """Scenario: first-time publish — no duplicate exists."""

    def test_dag_hash_is_deterministic(self) -> None:
        """Same topology must always produce the same dag_hash."""
        h1 = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        h2 = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_cache_miss_then_set_then_hit(self) -> None:
        """get_published returns None, set_published stores, get_published returns record."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        record = {
            "dag_hash": dag_hash,
            "workflow_id": "wf-001",
            "status": "published",
        }

        cache = _make_cache(fake_redis)

        # 1. No published workflow yet — cache miss.
        fake_redis.get.return_value = None
        assert cache.get_published(dag_hash) is None

        # 2. Publish — store in cache.
        cache.set_published(dag_hash, record)
        fake_redis.set.assert_called_once_with(
            f"wf:pub:{dag_hash}",
            json.dumps(record, default=str),
        )

        # 3. Re-query — cache hit returns the record.
        fake_redis.get.return_value = json.dumps(record, default=str)
        result = cache.get_published(dag_hash)
        assert result is not None
        assert result["workflow_id"] == "wf-001"
        assert result["status"] == "published"


# ---------------------------------------------------------------------------
# Test: publish duplicate detected
# ---------------------------------------------------------------------------


class TestPublishDuplicateDetected:
    """Scenario: same topology already published — duplicate detected."""

    def test_duplicate_returns_existing_record(self) -> None:
        """When the same dag_hash is published twice, get_published finds the first."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)

        existing_record = {
            "dag_hash": dag_hash,
            "workflow_id": "wf-original",
            "status": "published",
        }

        cache = _make_cache(fake_redis)

        # Pre-populate cache — simulate a prior publish.
        fake_redis.get.return_value = json.dumps(existing_record, default=str)

        # Re-computing the hash from the same topology must match.
        recomputed = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        assert recomputed == dag_hash

        # Duplicate detection: get_published returns the existing record.
        result = cache.get_published(dag_hash)
        assert result is not None
        assert result["workflow_id"] == "wf-original"

    def test_different_topology_produces_different_hash(self) -> None:
        """A different DAG layout must produce a different dag_hash."""
        h_original = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)

        different_nodes = [
            {"id": "n1", "type": "input/image"},
            {"id": "n2", "type": "engine/vlm"},
            {"id": "n3", "type": "end/final"},
        ]
        h_different = compute_dag_hash(different_nodes, EDGES, NODE_CONFIGS)

        assert h_original != h_different

    def test_different_config_produces_different_hash(self) -> None:
        """Same topology but different node config must produce a different dag_hash."""
        h_original = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)

        different_configs = {
            "n1": {},
            "n2": {"model": "paddleocr"},  # changed model
            "n3": {},
        }
        h_different = compute_dag_hash(NODES, EDGES, different_configs)

        assert h_original != h_different


# ---------------------------------------------------------------------------
# Test: task run tracking — first run
# ---------------------------------------------------------------------------


class TestTaskRunTrackingFirstRun:
    """Scenario: first task run for a workflow — tracking entry created."""

    def test_first_run_creates_tracking(self) -> None:
        """After the first append, exists() is True and get_task_runs returns [run-1]."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        workflow_hash = compute_workflow_hash(dag_hash, INPUT_FILES)

        cache = _make_cache(fake_redis)

        # exists() returns False before any tracking.
        fake_redis.exists.return_value = 0
        assert cache.exists(workflow_hash) is False

        # append_task_run — pipeline mock.
        _setup_pipeline(fake_redis, None)  # no existing entry
        cache.append_task_run(workflow_hash, dag_hash, "run-1")

        # Verify the stored payload.
        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["dag_hash"] == dag_hash
        assert stored["task_runs"] == ["run-1"]

        # exists() returns True after tracking.
        fake_redis.exists.return_value = 1
        assert cache.exists(workflow_hash) is True

        # get_task_runs returns the single run.
        entry = {"dag_hash": dag_hash, "task_runs": ["run-1"]}
        fake_redis.get.return_value = json.dumps(entry)
        assert cache.get_task_runs(workflow_hash) == ["run-1"]


# ---------------------------------------------------------------------------
# Test: task run tracking — subsequent runs + cap
# ---------------------------------------------------------------------------


class TestTaskRunTrackingSubsequentRuns:
    """Scenario: multiple task runs appended, capped at 10."""

    def test_multiple_runs_tracked(self) -> None:
        """Appending run-1, run-2, run-3 accumulates all three."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        workflow_hash = compute_workflow_hash(dag_hash, INPUT_FILES)

        cache = _make_cache(fake_redis)

        # --- run-1: empty start ---
        _setup_pipeline(fake_redis, None)
        cache.append_task_run(workflow_hash, dag_hash, "run-1")

        # --- run-2: existing = [run-1] ---
        existing_1 = {"dag_hash": dag_hash, "task_runs": ["run-1"]}
        _setup_pipeline(fake_redis, json.dumps(existing_1))
        cache.append_task_run(workflow_hash, dag_hash, "run-2")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["task_runs"] == ["run-1", "run-2"]

        # --- run-3: existing = [run-1, run-2] ---
        existing_2 = {"dag_hash": dag_hash, "task_runs": ["run-1", "run-2"]}
        _setup_pipeline(fake_redis, json.dumps(existing_2))
        cache.append_task_run(workflow_hash, dag_hash, "run-3")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["task_runs"] == ["run-1", "run-2", "run-3"]

    def test_cap_at_10_keeps_last_10(self) -> None:
        """When 12 runs are appended, only the last 10 are retained."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        workflow_hash = compute_workflow_hash(dag_hash, INPUT_FILES)

        cache = _make_cache(fake_redis)

        # Simulate 10 existing runs.
        existing_runs = [f"run-{i}" for i in range(10)]
        existing = {"dag_hash": dag_hash, "task_runs": existing_runs}

        # Append run-10 (11th entry) — should cap to last 10.
        _setup_pipeline(fake_redis, json.dumps(existing))
        cache.append_task_run(workflow_hash, dag_hash, "run-10")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert len(stored["task_runs"]) == 10
        # 10 existing (run-0..run-9) + 1 new (run-10) = 11 items; cap keeps last 10: run-1..run-10
        assert stored["task_runs"][0] == "run-1"
        assert stored["task_runs"][-1] == "run-10"

    def test_cap_evicts_oldest(self) -> None:
        """After 12 appends the two oldest are evicted."""
        fake_redis = MagicMock()
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        workflow_hash = compute_workflow_hash(dag_hash, INPUT_FILES)

        cache = _make_cache(fake_redis)

        # Simulate 11 existing runs (run-0 .. run-10).
        existing_runs = [f"run-{i}" for i in range(11)]
        existing = {"dag_hash": dag_hash, "task_runs": existing_runs}

        # Append run-11 — total 12, cap to last 10.
        _setup_pipeline(fake_redis, json.dumps(existing))
        cache.append_task_run(workflow_hash, dag_hash, "run-11")

        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert len(stored["task_runs"]) == 10
        # Oldest two (run-0, run-1) evicted.
        assert stored["task_runs"][0] == "run-2"
        assert stored["task_runs"][-1] == "run-11"


# ---------------------------------------------------------------------------
# Test: full publish -> run integration
# ---------------------------------------------------------------------------


class TestPublishThenRunIntegration:
    """End-to-end flow: publish workflow, then run a task, verify tracking."""

    def test_full_lifecycle(self) -> None:
        """Publish a workflow -> run a task -> published record exists + task run tracked."""
        fake_redis = MagicMock()
        cache = _make_cache(fake_redis)

        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)
        workflow_hash = compute_workflow_hash(dag_hash, INPUT_FILES)

        # --- Step 1: Publish ---
        publish_record = {
            "dag_hash": dag_hash,
            "workflow_id": "wf-001",
            "status": "published",
            "node_count": len(NODES),
        }

        # Cache is empty — no duplicate.
        fake_redis.get.return_value = None
        assert cache.get_published(dag_hash) is None

        # Publish the workflow.
        cache.set_published(dag_hash, publish_record)

        # Verify set_published was called with correct key and data.
        fake_redis.set.assert_called_with(
            f"wf:pub:{dag_hash}",
            json.dumps(publish_record, default=str),
        )

        # --- Step 2: Run task ---
        # Simulate published workflow is now in cache.
        fake_redis.get.return_value = json.dumps(publish_record, default=str)

        # Verify the published workflow is found (no 409 path here, it's the same publisher).
        published = cache.get_published(dag_hash)
        assert published is not None
        assert published["workflow_id"] == "wf-001"

        # No task runs yet.
        fake_redis.exists.return_value = 0
        assert cache.exists(workflow_hash) is False

        # Append first task run.
        _setup_pipeline(fake_redis, None)
        cache.append_task_run(workflow_hash, dag_hash, "task-run-abc123")

        # Verify stored tracking data.
        write_pipe = fake_redis.pipeline.return_value
        stored = json.loads(write_pipe.set.call_args[0][1])
        assert stored["dag_hash"] == dag_hash
        assert stored["task_runs"] == ["task-run-abc123"]

        # --- Step 3: Verify ---
        # exists() now returns True.
        fake_redis.exists.return_value = 1
        assert cache.exists(workflow_hash) is True

        # get_task_runs returns the tracked run.
        tracking_entry = {"dag_hash": dag_hash, "task_runs": ["task-run-abc123"]}
        fake_redis.get.return_value = json.dumps(tracking_entry)
        runs = cache.get_task_runs(workflow_hash)
        assert runs == ["task-run-abc123"]

        # get_dag_hash returns the correct dag_hash.
        assert cache.get_dag_hash(workflow_hash) == dag_hash

    def test_different_inputs_different_workflow_hash(self) -> None:
        """Same DAG but different input files must produce different workflow hashes."""
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)

        inputs_a = [{"name": "doc-a.pdf", "size": 1024}]
        inputs_b = [{"name": "doc-b.pdf", "size": 2048}]

        wh_a = compute_workflow_hash(dag_hash, inputs_a)
        wh_b = compute_workflow_hash(dag_hash, inputs_b)

        assert wh_a != wh_b

    def test_same_inputs_same_workflow_hash(self) -> None:
        """Same DAG and same input files must produce the same workflow hash."""
        dag_hash = compute_dag_hash(NODES, EDGES, NODE_CONFIGS)

        inputs = [{"name": "test.pdf", "size": 1024}]

        wh_1 = compute_workflow_hash(dag_hash, inputs)
        wh_2 = compute_workflow_hash(dag_hash, inputs)

        assert wh_1 == wh_2
