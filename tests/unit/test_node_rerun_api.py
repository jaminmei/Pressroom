"""Unit tests for node rerun API endpoint logic.

Tests POST /tasks/{task_id}/nodes/{node_id}/rerun — node-level rerun that
re-executes the target node and all its downstream nodes.

Since app.api.tasks imports Celery, these tests validate the core logic
(downstream computation, event deletion, partial re-execution) at the
service level.


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


def _four_node_workflow() -> WorkflowDefinition:
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


def _parallel_workflow() -> WorkflowDefinition:
    """upload → [ocr, model] → output"""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="upload-1", type="input/image", config={}),
            WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
            WorkflowNode(id="model-1", type="engine/model", config={}),
            WorkflowNode(id="output-1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
            WorkflowConnection(source="upload-1", target="model-1", target_port="image"),
            WorkflowConnection(source="ocr-1", target="output-1", target_port="input"),
            WorkflowConnection(source="model-1", target="output-1", target_port="input"),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_store(tmp_path):
    db_path = tmp_path / "rerun_test.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    metadata = MetaData()
    ExecutionEventRecord.__table__.to_metadata(metadata)
    with engine.begin() as conn:
        metadata.create_all(conn)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventStore(session_factory=session_factory)
    engine.dispose()


# ---------------------------------------------------------------------------
# Tests: Rerun scope computation
# ---------------------------------------------------------------------------


class TestRerunScope:
    def test_rerun_middle_node(self):
        """Rerun ocr-1 includes ocr-1 + downstream (model-1, output-1)."""
        dag = build_dag(_four_node_workflow())
        scope = _downstream_closure(dag, {"ocr-1"})
        assert scope == {"ocr-1", "model-1", "output-1"}

    def test_rerun_leaf_node(self):
        """Rerun output-1 only includes output-1 (no downstream)."""
        dag = build_dag(_four_node_workflow())
        scope = _downstream_closure(dag, {"output-1"})
        assert scope == {"output-1"}

    def test_rerun_parallel_branch(self):
        """Rerun ocr-1 in parallel workflow: scope is ocr-1 + output-1."""
        dag = build_dag(_parallel_workflow())
        scope = _downstream_closure(dag, {"ocr-1"})
        assert scope == {"ocr-1", "output-1"}
        assert "model-1" not in scope  # model-1 is a sibling, not downstream


# ---------------------------------------------------------------------------
# Tests: Rerun re-execution
# ---------------------------------------------------------------------------


class TestRerunReExecution:
    @pytest.mark.asyncio()
    async def test_rerun_completed_node(self, event_store, tmp_path):
        """Rerun a completed node re-executes it + downstream, preserves upstream."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _four_node_workflow()
        run_id = "rerun-1"

        # All nodes completed
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="ocr"))
        )
        event_store.append(
            _make_event(run_id, "model-1", "completed", 2, "engine/model", NodeOutput(text="model"))
        )
        event_store.append(_make_event(run_id, "output-1", "completed", 3, "end/final"))

        # Rerun from ocr-1
        rerun_scope = {"ocr-1", "model-1", "output-1"}
        event_store.delete_events_for_nodes(run_id, rerun_scope)

        executed: list[str] = []

        async def tracking_executor(node, inputs):
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes={"ocr-1"},
        )

        assert "upload-1" not in executed
        assert "ocr-1" in executed
        assert "model-1" in executed
        assert "output-1" in state.completed

    @pytest.mark.asyncio()
    async def test_rerun_failed_node(self, event_store, tmp_path):
        """Rerun a failed node re-executes it + downstream."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _four_node_workflow()
        run_id = "rerun-2"

        # upload ok, ocr ok, model failed, output skipped
        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="ocr"))
        )
        event_store.append(_make_event(run_id, "model-1", "failed", 2, "engine/model"))

        rerun_scope = {"model-1", "output-1"}
        event_store.delete_events_for_nodes(run_id, rerun_scope)

        executed: list[str] = []

        async def tracking_executor(node, inputs):
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes={"model-1"},
        )

        assert "upload-1" not in executed
        assert "ocr-1" not in executed
        assert "model-1" in executed
        assert "output-1" in state.completed

    @pytest.mark.asyncio()
    async def test_rerun_preserves_upstream_output(self, event_store, tmp_path):
        """Rerun node receives upstream output from pre-filled state."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _four_node_workflow()
        run_id = "rerun-3"

        event_store.append(
            _make_event(
                run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="original img")
            )
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="original ocr"))
        )

        event_store.delete_events_for_nodes(run_id, {"ocr-1", "model-1", "output-1"})

        received_inputs: dict[str, dict[str, str]] = {}

        async def tracking_executor(node, inputs):
            received_inputs[node.node_id] = {k: v.text for k, v in inputs.items()}
            return NodeOutput(text=f"rerun {node.node_id}")

        await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes={"ocr-1"},
        )

        # ocr-1 receives upload-1's pre-filled output
        assert "images" in received_inputs["ocr-1"]
        assert received_inputs["ocr-1"]["images"] == "original img"
        # model-1 receives ocr-1's NEW output (from rerun)
        assert "image" in received_inputs["model-1"]
        assert received_inputs["model-1"]["image"] == "rerun ocr-1"

    @pytest.mark.asyncio()
    async def test_rerun_parallel_branch_does_not_affect_sibling(self, event_store, tmp_path):
        """Rerunning one branch in a parallel workflow doesn't re-execute the other."""
        registry = NodeRegistryService()
        storage = LocalStorageAdapter(storage_root=str(tmp_path / "storage"))
        scheduler = DAGScheduler(event_store=event_store, node_registry=registry, storage=storage)
        wf = _parallel_workflow()
        run_id = "rerun-4"

        event_store.append(
            _make_event(run_id, "upload-1", "completed", 0, "input/image", NodeOutput(text="img"))
        )
        event_store.append(
            _make_event(run_id, "ocr-1", "completed", 1, output=NodeOutput(text="ocr"))
        )
        event_store.append(
            _make_event(run_id, "model-1", "completed", 2, "engine/model", NodeOutput(text="model"))
        )
        event_store.append(_make_event(run_id, "output-1", "completed", 3, "end/final"))

        # Rerun only ocr-1
        event_store.delete_events_for_nodes(run_id, {"ocr-1", "output-1"})

        executed: list[str] = []

        async def tracking_executor(node, inputs):
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id=run_id,
            start_nodes={"ocr-1"},
        )

        assert "ocr-1" in executed
        assert "model-1" not in executed  # sibling not rerun
