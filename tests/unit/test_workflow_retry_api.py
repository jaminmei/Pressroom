"""Unit tests for workflow retry API endpoint logic.

Tests POST /tasks/{task_id}/retry — workflow-level retry that re-executes
all failed nodes and their downstream.

Since app.api.tasks imports Celery which may not be available in unit test
environments, these tests validate the core logic (finding failed nodes,
computing downstream, event deletion) at the service level.


"""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import ExecutionEvent, NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.dag_scheduler import DAGScheduler, _downstream_closure, build_dag
from app.services.event_store import EventStore
from app.services.node_registry import NodeRegistryService
from app.storage.local import LocalStorageAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    run_id: str,
    node_id: str,
    event_type: str,
    sequence: int,
    node_type: str = "engine/ocr",
    output: NodeOutput | None = None,
) -> ExecutionEvent:
    from app.models.execution import ErrorInfo

    return ExecutionEvent(
        event_id=f"{run_id}-{node_id}-{sequence}",
        workflow_run_id=run_id,
        node_id=node_id,
        node_type=node_type,
        event_type=event_type,
        sequence=sequence,
        timestamp=1000000.0 + sequence,
        output=output,
        error=ErrorInfo(type="RuntimeError", message="test error")
        if event_type == "failed"
        else None,
    )


def _simple_workflow() -> WorkflowDefinition:
    """upload → ocr → model → output"""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="upload-1", type="input/image", config={}),
            WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
            WorkflowNode(id="model-1", type="engine/model", config={}),
            WorkflowNode(id="output-1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
            WorkflowConnection(source="ocr-1", target="model-1", target_port="image"),
            WorkflowConnection(source="model-1", target="output-1", target_port="input"),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_store(tmp_path):
    db_path = tmp_path / "retry_test.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    metadata = MetaData()
    ExecutionEventRecord.__table__.to_metadata(metadata)
    with engine.begin() as conn:
        metadata.create_all(conn)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventStore(session_factory=session_factory)
    engine.dispose()


# ---------------------------------------------------------------------------
# Tests: Finding failed nodes from events
# ---------------------------------------------------------------------------


class TestFindFailedNodes:
    def test_identifies_failed_nodes(self, event_store):
        """Scan events to find all failed node IDs."""
        run_id = "run-1"
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="ocr"))
        )
        event_store.append(_make_event(run_id, "model-1", "failed", 2, "engine/model"))
        event_store.append(_make_event(run_id, "output-1", "skipped", 3, "end/final"))

        events = event_store.get_events(run_id)
        failed_nodes = {e.node_id for e in events if e.event_type == "failed"}
        assert failed_nodes == {"model-1"}

    def test_identifies_multiple_failed_nodes(self, event_store):
        """Multiple failed nodes are all identified."""
        run_id = "run-2"
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(_make_event(run_id, "ocr-1", "failed", 1))
        event_store.append(_make_event(run_id, "model-1", "failed", 2, "engine/model"))

        events = event_store.get_events(run_id)
        failed_nodes = {e.node_id for e in events if e.event_type == "failed"}
        assert failed_nodes == {"ocr-1", "model-1"}

    def test_no_failed_nodes(self, event_store):
        """When all nodes completed, no failed nodes found."""
        run_id = "run-3"
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="ocr"))
        )

        events = event_store.get_events(run_id)
        failed_nodes = {e.node_id for e in events if e.event_type == "failed"}
        assert failed_nodes == set()


# ---------------------------------------------------------------------------
# Tests: Computing rerun scope from failed nodes
# ---------------------------------------------------------------------------


class TestRetryScopeComputation:
    def test_single_failed_node_scope(self):
        """Failed node + downstream = rerun scope."""
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"model-1"})
        assert scope == {"model-1", "output-1"}

    def test_multiple_failed_nodes_scope(self):
        """Multiple failed nodes' scopes are merged."""
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"ocr-1", "model-1"})
        assert scope == {"ocr-1", "model-1", "output-1"}

    def test_root_failed_scope(self):
        """If root fails, entire DAG is in scope."""
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"upload-1"})
        assert scope == {"upload-1", "ocr-1", "model-1", "output-1"}


# ---------------------------------------------------------------------------
# Tests: Event deletion + partial re-execution
# ---------------------------------------------------------------------------


class TestRetryReExecution:
    @pytest.mark.asyncio()
    async def test_retry_preserves_completed_upstream(self, event_store, tmp_path):
        """After retry, completed upstream nodes are NOT re-executed."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _simple_workflow()
        run_id = "retry-1"

        # Seed events for a failed run: upload ok, ocr ok, model failed
        event_store.append(_make_event(run_id, "upload-1", "started", 0, "input/image"))
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 1, "input/image", NodeOutput(text="img"))
        )
        event_store.append(_make_event(run_id, "ocr-1", "started", 2))
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 3, output=NodeOutput(text="ocr result"))
        )
        event_store.append(_make_event(run_id, "model-1", "started", 4, "engine/model"))
        event_store.append(_make_event(run_id, "model-1", "failed", 5, "engine/model"))

        # Simulate retry: find failed nodes, compute scope, delete, re-run
        events = event_store.get_events(run_id)
        failed_nodes = {e.node_id for e in events if e.event_type == "failed"}
        assert failed_nodes == {"model-1"}

        dag = build_dag(wf)
        rerun_scope = _downstream_closure(dag, failed_nodes)
        assert rerun_scope == {"model-1", "output-1"}

        event_store.delete_events_for_nodes(run_id, rerun_scope)

        # Track which nodes execute
        executed: list[str] = []

        async def tracking_executor(node, inputs):
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes=failed_nodes,
        )

        assert "upload-1" not in executed  # pre-filled
        assert "ocr-1" not in executed  # pre-filled
        assert "model-1" in executed  # re-executed
        assert "output-1" in state.completed

    @pytest.mark.asyncio()
    async def test_retry_multiple_failed(self, event_store, tmp_path):
        """Retry with multiple failed nodes re-executes them all."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _simple_workflow()
        run_id = "retry-2"

        # upload ok, ocr failed, model failed
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(_make_event(run_id, "ocr-1", "failed", 1))
        event_store.append(_make_event(run_id, "model-1", "failed", 2, "engine/model"))

        events = event_store.get_events(run_id)
        failed_nodes = {e.node_id for e in events if e.event_type == "failed"}
        dag = build_dag(wf)
        rerun_scope = _downstream_closure(dag, failed_nodes)
        event_store.delete_events_for_nodes(run_id, rerun_scope)

        executed: list[str] = []

        async def tracking_executor(node, inputs):
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes=failed_nodes,
        )

        assert "upload-1" not in executed
        assert "ocr-1" in executed
        assert "model-1" in executed
        assert "output-1" in state.completed
