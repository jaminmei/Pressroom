from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import NodeOutput
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.dag_scheduler import (
    DAGNode,
    DAGRunResult,
    DAGScheduler,
    _downstream_closure,
    build_dag,
    find_ready_nodes,
    resolve_inputs,
    validate_dag,
)
from app.services.event_store import EventStore
from app.services.node_registry import NodeRegistryService
from app.storage.local import LocalStorageAdapter

SessionFactory = Callable[[], Session]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_store(tmp_path) -> Iterator[tuple[EventStore, SessionFactory]]:
    db_path = tmp_path / "dag_test.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    metadata = MetaData()
    ExecutionEventRecord.__table__.to_metadata(metadata)
    with engine.begin() as conn:
        metadata.create_all(conn)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventStore(session_factory=session_factory), session_factory
    engine.dispose()


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


@pytest.fixture()
def storage(tmp_path) -> LocalStorageAdapter:
    return LocalStorageAdapter(storage_root=str(tmp_path / "storage"))


def _simple_workflow(file_path: str = "") -> WorkflowDefinition:
    """upload → ocr → output"""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(
                id="upload-1", type="input/image", config={"file": file_path} if file_path else {}
            ),
            WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
            WorkflowNode(id="output-1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
            WorkflowConnection(source="ocr-1", target="output-1", target_port="input"),
        ],
    )


def _parallel_workflow(file_path: str = "") -> WorkflowDefinition:
    """upload → [ocr, vlm] → output"""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(
                id="upload-1", type="input/image", config={"file": file_path} if file_path else {}
            ),
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


def _cycle_workflow() -> WorkflowDefinition:
    """A → B → A (cycle)"""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="A", type="input/image", config={}),
            WorkflowNode(id="B", type="engine/ocr", config={}),
        ],
        connections=[
            WorkflowConnection(source="A", target="B", target_port="images"),
            WorkflowConnection(source="B", target="A", target_port="source"),
        ],
    )


def _unknown_type_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="n1", type="engine/unknown", config={}),
        ],
        connections=[],
    )


# ---------------------------------------------------------------------------
# build_dag tests
# ---------------------------------------------------------------------------


class TestBuildDag:
    def test_simple_linear(self):
        dag = build_dag(_simple_workflow())
        assert set(dag.nodes.keys()) == {"upload-1", "ocr-1", "output-1"}
        assert dag.roots == {"upload-1"}
        assert dag.nodes["ocr-1"].named_inputs == {"images": "upload-1"}
        assert dag.nodes["ocr-1"].dependencies == {"upload-1"}
        assert dag.downstream["upload-1"] == {"ocr-1"}

    def test_parallel(self):
        dag = build_dag(_parallel_workflow())
        assert dag.roots == {"upload-1"}
        assert dag.nodes["model-1"].named_inputs == {"image": "upload-1"}
        assert dag.downstream["upload-1"] == {"ocr-1", "model-1"}

    def test_no_connections(self):
        wf = WorkflowDefinition(
            nodes=[WorkflowNode(id="a", type="input/image", config={})],
            connections=[],
        )
        dag = build_dag(wf)
        assert dag.roots == {"a"}
        assert not dag.nodes["a"].dependencies


# ---------------------------------------------------------------------------
# validate_dag tests
# ---------------------------------------------------------------------------


class TestValidateDag:
    def test_valid_workflow(self, registry: NodeRegistryService):
        dag = build_dag(_simple_workflow())
        errors = validate_dag(dag, registry)
        assert errors == []

    def test_cycle_detection(self, registry: NodeRegistryService):
        dag = build_dag(_cycle_workflow())
        errors = validate_dag(dag, registry)
        assert any("cycle" in e.lower() for e in errors)

    def test_unknown_node_type(self, registry: NodeRegistryService):
        dag = build_dag(_unknown_type_workflow())
        errors = validate_dag(dag, registry)
        assert any("unknown type" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# find_ready_nodes tests
# ---------------------------------------------------------------------------


class TestFindReadyNodes:
    def test_only_roots_ready(self):
        dag = build_dag(_simple_workflow())
        ready = find_ready_nodes(dag, completed=set(), running=set())
        assert [n.node_id for n in ready] == ["upload-1"]

    def test_after_first_completed(self):
        dag = build_dag(_simple_workflow())
        ready = find_ready_nodes(dag, completed={"upload-1"}, running=set())
        assert [n.node_id for n in ready] == ["ocr-1"]

    def test_parallel_ready(self):
        dag = build_dag(_parallel_workflow())
        ready = find_ready_nodes(dag, completed={"upload-1"}, running=set())
        ids = [n.node_id for n in ready]
        assert "model-1" in ids
        assert "ocr-1" in ids

    def test_running_excluded(self):
        dag = build_dag(_simple_workflow())
        ready = find_ready_nodes(dag, completed=set(), running={"upload-1"})
        assert ready == []

    def test_all_completed(self):
        dag = build_dag(_simple_workflow())
        ready = find_ready_nodes(dag, completed={"upload-1", "ocr-1", "output-1"}, running=set())
        assert ready == []


# ---------------------------------------------------------------------------
# resolve_inputs tests
# ---------------------------------------------------------------------------


class TestResolveInputs:
    def test_basic_resolution(self):
        node = DAGNode(
            node_id="ocr-1",
            node_type="engine/ocr",
            config={},
            named_inputs={"images": "upload-1"},
            dependencies={"upload-1"},
        )
        state = {"upload-1": NodeOutput(text="image data")}
        inputs = resolve_inputs(node, state)
        assert "images" in inputs
        assert inputs["images"].text == "image data"

    def test_multi_port_resolution(self):
        node = DAGNode(
            node_id="model-1",
            node_type="engine/model",
            config={},
            named_inputs={"image": "upload-1", "text": "ocr-1"},
            dependencies={"upload-1", "ocr-1"},
        )
        state = {
            "upload-1": NodeOutput(text="img"),
            "ocr-1": NodeOutput(text="ocr result"),
        }
        inputs = resolve_inputs(node, state)
        assert inputs["image"].text == "img"
        assert inputs["text"].text == "ocr result"


# ---------------------------------------------------------------------------
# DAGScheduler.run integration tests
# ---------------------------------------------------------------------------


def _make_executor(
    outputs: dict[str, NodeOutput] | None = None,
    fail_nodes: set[str] | None = None,
):
    """Create a simple node executor for testing."""
    _outputs = outputs or {}
    _fail_nodes = fail_nodes or set()

    async def executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node.node_id in _fail_nodes:
            raise RuntimeError(f"Node {node.node_id} failed")
        if node.node_id in _outputs:
            return _outputs[node.node_id]
        return NodeOutput(text=f"output from {node.node_id}")

    return executor


class TestDAGSchedulerRun:
    @pytest.fixture()
    def image_file(self, tmp_path) -> str:
        p = tmp_path / "test.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return str(p)

    @pytest.mark.asyncio()
    async def test_linear_execution(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(),
        )
        state = result.completed

        assert "upload-1" in state
        assert "ocr-1" in state
        assert "output-1" in state

    @pytest.mark.asyncio()
    async def test_parallel_execution(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            _parallel_workflow(file_path=image_file),
            node_executor=_make_executor(),
        )
        state = result.completed

        assert len(state) == 4
        assert "upload-1" in state
        assert "ocr-1" in state
        assert "model-1" in state
        assert "output-1" in state

    @pytest.mark.asyncio()
    async def test_events_persisted(self, event_store, registry, storage, image_file):
        es, sf = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(),
            run_id="test-run-1",
        )

        events = es.get_events("test-run-1")
        # Each node emits: started + completed = 2 events, 3 nodes = 6 events
        assert len(events) >= 6
        event_types = [e.event_type for e in events]
        assert event_types.count("started") == 3
        assert event_types.count("completed") == 3

    @pytest.mark.asyncio()
    async def test_branch_failure_isolation(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        # ocr-1 fails, model-1 should still complete
        result = await scheduler.run(
            _parallel_workflow(file_path=image_file),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
        )
        state = result.completed

        assert "upload-1" in state
        assert "model-1" in state
        # ocr-1 should not be in completed state (failed)
        assert "ocr-1" not in state

    @pytest.mark.asyncio()
    async def test_skip_propagation(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        # Simple workflow: upload → ocr → output, ocr fails
        _ = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="skip-test",
        )

        events = es.get_events("skip-test")
        skipped = [e for e in events if e.event_type == "skipped"]
        # output-1 should be skipped because ocr-1 failed
        assert any(e.node_id == "output-1" for e in skipped)

    @pytest.mark.asyncio()
    async def test_invalid_workflow_raises(self, event_store, registry, storage):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        with pytest.raises(ValueError, match="validation failed"):
            await scheduler.run(
                _cycle_workflow(),
                node_executor=_make_executor(),
            )

    @pytest.mark.asyncio()
    async def test_compute_state_matches_events(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        run_id = "state-match-test"
        await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(),
            run_id=run_id,
        )

        state = es.compute_state(run_id)
        assert len(state) == 3
        assert all(isinstance(v, NodeOutput) for v in state.values())

    @pytest.mark.asyncio()
    async def test_input_binding_resolves_placeholder(
        self, event_store, registry, storage, image_file
    ):
        """Input node uses binding file_path when config contains placeholder ``$file_0``."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        wf = _simple_workflow(file_path="$file_0")
        bindings = {
            "upload-1": TaskInputFile(
                file_path=image_file,
                filename="test.png",
                mime_type="image/png",
                size_bytes=100,
            ),
        }

        result = await scheduler.run(
            wf,
            node_executor=_make_executor(),
            input_bindings=bindings,
        )

        assert "upload-1" in result.completed
        assert result.completed["upload-1"].metadata["filename"] == "test.png"

    @pytest.mark.asyncio()
    async def test_input_binding_missing_falls_back_to_config(
        self, event_store, registry, storage, image_file
    ):
        """When no binding for a node, falls back to config.file."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        wf = _simple_workflow(file_path=image_file)

        result = await scheduler.run(
            wf,
            node_executor=_make_executor(),
            input_bindings={},  # no binding for upload-1
        )

        assert "upload-1" in result.completed

    @pytest.mark.asyncio()
    async def test_input_binding_placeholder_without_binding_fails(
        self, event_store, registry, storage
    ):
        """Placeholder file path without binding raises ValueError and node is marked failed."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        wf = _simple_workflow(file_path="$file_0")
        cancelled = False

        def cancel_check() -> bool:
            return cancelled

        async def run_with_cancel() -> DAGRunResult:
            return await scheduler.run(
                wf,
                node_executor=_make_executor(),
                cancel_check=cancel_check,
            )

        task = asyncio.ensure_future(run_with_cancel())
        await asyncio.sleep(0.3)
        cancelled = True
        result = await task

        assert "upload-1" not in result.completed
        assert "upload-1" in result.failed
        assert "Input file not found" in result.failed["upload-1"]

    @pytest.mark.asyncio()
    async def test_failed_node_error_message_captured(
        self, event_store, registry, storage, image_file
    ):
        """Failed executor node error message is captured in DAGRunResult.failed."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="fail-msg-test",
        )

        assert "ocr-1" not in result.completed
        assert "ocr-1" in result.failed
        assert result.failed["ocr-1"] == "Node ocr-1 failed"

    @pytest.mark.asyncio()
    async def test_downstream_nodes_failed_when_upstream_fails(
        self, event_store, registry, storage, image_file
    ):
        """Downstream nodes are captured in DAGRunResult.failed when upstream fails."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="downstream-fail-test",
        )

        assert "output-1" not in result.completed
        assert "output-1" in result.failed  # dependency failure is treated as failed
        assert result.failed["output-1"] == "dependency failed"

    @pytest.mark.asyncio()
    async def test_orchestrator_status_propagation(
        self, event_store, registry, storage, image_file
    ):
        """Simulate orchestrator _execute_dag: FAILED nodes propagate to node_states."""
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
        )

        node_states: dict[str, str] = {}
        for node_id, _output in result.completed.items():
            node_states[node_id] = "completed"
        for node_id, error_msg in result.failed.items():
            node_states[node_id] = f"failed: {error_msg}"
        for node_id in result.skipped:
            node_states[node_id] = "skipped"

        assert node_states["upload-1"] == "completed"
        assert node_states["ocr-1"] == "failed: Node ocr-1 failed"
        assert "output-1" in node_states  # dependency-failed node is propagated


class TestParsePageRange:
    def test_single_page(self):
        from app.services.dag_scheduler import DAGScheduler

        assert DAGScheduler._parse_page_range("1", 10) == [1]

    def test_page_range(self):
        from app.services.dag_scheduler import DAGScheduler

        assert DAGScheduler._parse_page_range("1-3", 10) == [1, 2, 3]

    def test_all_pages(self):
        from app.services.dag_scheduler import DAGScheduler

        assert DAGScheduler._parse_page_range("all", 5) == [1, 2, 3, 4, 5]

    def test_single_page_out_of_range(self):
        from app.services.dag_scheduler import DAGScheduler

        with pytest.raises(ValueError, match="out of range"):
            DAGScheduler._parse_page_range("11", 10)

    def test_invalid_range(self):
        from app.services.dag_scheduler import DAGScheduler

        with pytest.raises(ValueError, match="Invalid page range"):
            DAGScheduler._parse_page_range("5-3", 10)

    def test_invalid_format(self):
        from app.services.dag_scheduler import DAGScheduler

        with pytest.raises(ValueError, match="Invalid pages value"):
            DAGScheduler._parse_page_range("abc", 10)

    def test_range_exceeds_total(self):
        from app.services.dag_scheduler import DAGScheduler

        with pytest.raises(ValueError, match="Invalid page range"):
            DAGScheduler._parse_page_range("1-15", 10)


# ---------------------------------------------------------------------------
# _downstream_closure tests
# ---------------------------------------------------------------------------


class TestDownstreamClosure:
    def test_single_node(self):
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"ocr-1"})
        assert scope == {"ocr-1", "output-1"}

    def test_root_node(self):
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"upload-1"})
        assert scope == {"upload-1", "ocr-1", "output-1"}

    def test_leaf_node(self):
        dag = build_dag(_simple_workflow())
        scope = _downstream_closure(dag, {"output-1"})
        assert scope == {"output-1"}

    def test_parallel_branch(self):
        dag = build_dag(_parallel_workflow())
        scope = _downstream_closure(dag, {"ocr-1"})
        assert scope == {"ocr-1", "output-1"}

    def test_multiple_start_nodes(self):
        dag = build_dag(_parallel_workflow())
        scope = _downstream_closure(dag, {"ocr-1", "model-1"})
        assert scope == {"ocr-1", "model-1", "output-1"}


# ---------------------------------------------------------------------------
# Partial execution (start_nodes) tests
# ---------------------------------------------------------------------------


class TestPartialExecution:
    @pytest.fixture()
    def image_file(self, tmp_path) -> str:
        p = tmp_path / "test.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return str(p)

    @pytest.mark.asyncio()
    async def test_prefills_completed_state_from_event_store(
        self, event_store, registry, storage, image_file
    ):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)
        wf = _simple_workflow(file_path=image_file)

        # First: full run to populate event store
        await scheduler.run(wf, node_executor=_make_executor(), run_id="partial-1")
        first_state = es.compute_state("partial-1")
        assert "upload-1" in first_state

        # Delete ocr-1 and output-1 events (simulating API layer cleanup)
        es.delete_events_for_nodes("partial-1", {"ocr-1", "output-1"})

        # Second: partial run starting from ocr-1
        state = await scheduler.run(
            wf,
            node_executor=_make_executor(),
            run_id="partial-1",
            start_nodes={"ocr-1"},
        )

        # upload-1 was pre-filled, ocr-1 and output-1 re-executed
        assert "ocr-1" in state.completed
        assert "output-1" in state.completed

    @pytest.mark.asyncio()
    async def test_skips_upstream_nodes(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)
        wf = _simple_workflow(file_path=image_file)

        # Full run
        await scheduler.run(wf, node_executor=_make_executor(), run_id="skip-upstream")

        # Track which engine nodes get executed in partial run
        # (end/final nodes bypass the executor, so only track engine nodes)
        executed: list[str] = []

        async def tracking_executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        # Delete downstream events
        es.delete_events_for_nodes("skip-upstream", {"ocr-1", "output-1"})

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id="skip-upstream",
            start_nodes={"ocr-1"},
        )

        # upload-1 not re-executed (engine nodes only)
        assert "upload-1" not in executed
        # ocr-1 was re-executed via executor
        assert "ocr-1" in executed
        # output-1 (end/final) is dispatched but uses built-in handler, check state
        assert "output-1" in state.completed

    @pytest.mark.asyncio()
    async def test_downstream_included_in_rerun(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        # A → B → C → D
        wf = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="A", type="input/image", config={"file": image_file}),
                WorkflowNode(id="B", type="engine/ocr", config={}),
                WorkflowNode(id="C", type="engine/model", config={}),
                WorkflowNode(id="D", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="A", target="B", target_port="images"),
                WorkflowConnection(source="B", target="C", target_port="image"),
                WorkflowConnection(source="C", target="D", target_port="input"),
            ],
        )

        # Full run
        await scheduler.run(wf, node_executor=_make_executor(), run_id="chain-rerun")
        es.delete_events_for_nodes("chain-rerun", {"B", "C", "D"})

        executed: list[str] = []

        async def tracking_executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
            executed.append(node.node_id)
            return NodeOutput(text=f"rerun {node.node_id}")

        state = await scheduler.run(
            wf,
            node_executor=tracking_executor,
            run_id="chain-rerun",
            start_nodes={"B"},
        )

        # A not re-executed, B and C via executor, D via built-in handler
        assert "A" not in executed
        assert "B" in executed
        assert "C" in executed
        assert "D" in state.completed

    @pytest.mark.asyncio()
    async def test_start_nodes_none_runs_all(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        state = await scheduler.run(
            _simple_workflow(file_path=image_file),
            node_executor=_make_executor(),
            run_id="full-run",
            start_nodes=None,
        )

        assert len(state.completed) == 3

    @pytest.mark.asyncio()
    async def test_events_emitted_for_rerun_nodes(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)
        wf = _simple_workflow(file_path=image_file)

        # Full run
        await scheduler.run(wf, node_executor=_make_executor(), run_id="evt-test")

        # Delete downstream events and re-run
        es.delete_events_for_nodes("evt-test", {"ocr-1", "output-1"})
        await scheduler.run(
            wf,
            node_executor=_make_executor(),
            run_id="evt-test",
            start_nodes={"ocr-1"},
        )

        all_events = es.get_events("evt-test")
        # Check that ocr-1 and output-1 have new completed events
        ocr_events = [e for e in all_events if e.node_id == "ocr-1" and e.event_type == "completed"]
        output_events = [
            e for e in all_events if e.node_id == "output-1" and e.event_type == "completed"
        ]
        assert len(ocr_events) >= 1
        assert len(output_events) >= 1
