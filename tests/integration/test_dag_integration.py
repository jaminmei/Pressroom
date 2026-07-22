"""Integration tests for DAG scheduler — event sourcing, parallel execution,
multi-input resolution, and branch failure isolation.

Tasks 11.1–11.4 from the doctags-removal-flatten-json change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import NodeOutput
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.dag_scheduler import DAGNode, DAGScheduler
from app.services.event_store import EventStore
from app.services.node_registry import NodeRegistryService
from app.storage.local import LocalStorageAdapter

SessionFactory = Callable[[], Session]

# Node registry reference (real port names):
#   input/image:       ports=[] (source)
#   input/text:         ports=[] (source)
#   processor/image_enhance: ports=[('image', ['image/*'], True)]
#   engine/ocr:         ports=[('images', ['image/*', ...], True)]
#   engine/model:       ports=[('image', [...], False), ('text', [...], False)]
#   end/final:          ports=[('input', ['text/raw', 'text/plain', ...], True)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event_store(tmp_path) -> Iterator[tuple[EventStore, SessionFactory]]:
    db_path = tmp_path / "dag_integration.sqlite3"
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


@pytest.fixture()
def image_file(tmp_path) -> str:
    p = tmp_path / "test.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return str(p)


def _bindings(image_path: str) -> dict[str, TaskInputFile]:
    return {
        "upload-1": TaskInputFile(file_path=image_path, filename="test.png", mime_type="image/png"),
        "img-src": TaskInputFile(file_path=image_path, filename="test.png", mime_type="image/png"),
    }


@pytest.fixture()
def text_file(tmp_path) -> str:
    p = tmp_path / "test.txt"
    p.write_text("sample text input")
    return str(p)


def _make_executor(
    outputs: dict[str, NodeOutput] | None = None,
    fail_nodes: set[str] | None = None,
    capture: dict | None = None,
):
    _outputs = outputs or {}
    _fail_nodes = fail_nodes or set()

    async def executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if capture is not None:
            capture[node.node_id] = dict(inputs)
        if node.node_id in _fail_nodes:
            raise RuntimeError(f"Node {node.node_id} failed")
        if node.node_id in _outputs:
            return _outputs[node.node_id]
        return NodeOutput(text=f"output from {node.node_id}")

    return executor


# ---------------------------------------------------------------------------
# 11.1 Sequential workflow with event log persistence
# ---------------------------------------------------------------------------


class TestSequentialWorkflow:
    """End-to-end: linear input/image → engine/ocr → end/final."""

    @staticmethod
    def _sequential_wf() -> WorkflowDefinition:
        return WorkflowDefinition(
            nodes=[
                WorkflowNode(id="upload-1", type="input/image", config={}),
                WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
                WorkflowNode(id="output-1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
                WorkflowConnection(source="ocr-1", target="output-1", target_port="input"),
            ],
        )

    @pytest.mark.asyncio()
    async def test_all_nodes_complete(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._sequential_wf(),
            node_executor=_make_executor(),
            run_id="seq-1",
            input_bindings=_bindings(image_file),
        )

        assert len(result.completed) == 3
        for nid in ("upload-1", "ocr-1", "output-1"):
            assert nid in result.completed

    @pytest.mark.asyncio()
    async def test_events_persisted_per_node(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            self._sequential_wf(),
            node_executor=_make_executor(),
            run_id="seq-events",
            input_bindings=_bindings(image_file),
        )

        events = es.get_events("seq-events")
        # 3 nodes × 2 events each (started + completed) = 6
        assert len(events) == 6

        by_node: dict[str, list[str]] = {}
        for e in events:
            by_node.setdefault(e.node_id, []).append(e.event_type)

        for nid in ("upload-1", "ocr-1", "output-1"):
            assert by_node[nid] == ["started", "completed"], f"{nid}"

    @pytest.mark.asyncio()
    async def test_sequence_numbers_strictly_increasing(
        self, event_store, registry, storage, image_file
    ):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            self._sequential_wf(),
            node_executor=_make_executor(),
            run_id="seq-seq",
            input_bindings=_bindings(image_file),
        )

        events = es.get_events("seq-seq")
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)

    @pytest.mark.asyncio()
    async def test_compute_state_returns_all_outputs(
        self, event_store, registry, storage, image_file
    ):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            self._sequential_wf(),
            node_executor=_make_executor(),
            run_id="seq-state",
            input_bindings=_bindings(image_file),
        )

        state = es.compute_state("seq-state")
        assert len(state) == 3
        assert all(isinstance(v, NodeOutput) for v in state.values())


# ---------------------------------------------------------------------------
# 11.2 Parallel DAG execution
# ---------------------------------------------------------------------------


class TestParallelDAG:
    """End-to-end: upload → [ocr, model] → output."""

    @staticmethod
    def _parallel_wf() -> WorkflowDefinition:
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

    @pytest.mark.asyncio()
    async def test_parallel_branches_complete(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(),
            run_id="par-1",
            input_bindings=_bindings(image_file),
        )

        assert len(result.completed) == 4
        assert "ocr-1" in result.completed
        assert "model-1" in result.completed

    @pytest.mark.asyncio()
    async def test_parallel_event_count(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(),
            run_id="par-events",
            input_bindings=_bindings(image_file),
        )

        events = es.get_events("par-events")
        # 4 nodes × 2 events = 8
        assert len(events) == 8
        event_types = [e.event_type for e in events]
        assert event_types.count("started") == 4
        assert event_types.count("completed") == 4

    @pytest.mark.asyncio()
    async def test_parallel_nodes_start_events(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(),
            run_id="par-order",
            input_bindings=_bindings(image_file),
        )

        events = es.get_events("par-order")
        started_nodes = {e.node_id for e in events if e.event_type == "started"}

        # Both parallel nodes should have started
        assert "ocr-1" in started_nodes
        assert "model-1" in started_nodes


# ---------------------------------------------------------------------------
# 11.3 VLM multi-input with named ports
# ---------------------------------------------------------------------------


class TestVLMMultiInput:
    """engine/model receives image + text inputs via named ports."""

    @staticmethod
    def _vlm_wf() -> WorkflowDefinition:
        return WorkflowDefinition(
            nodes=[
                WorkflowNode(id="img-src", type="input/image", config={}),
                WorkflowNode(id="text-src", type="input/text", config={}),
                WorkflowNode(
                    id="model-1", type="engine/model", config={"text_input_role": "context"}
                ),
                WorkflowNode(id="output-1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="img-src", target="model-1", target_port="image"),
                WorkflowConnection(source="text-src", target="model-1", target_port="text"),
                WorkflowConnection(source="model-1", target="output-1", target_port="input"),
            ],
        )

    @pytest.mark.asyncio()
    async def test_vlm_receives_both_inputs(
        self, event_store, registry, storage, image_file, text_file
    ):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)
        captured: dict[str, dict] = {}

        bindings = {
            "img-src": TaskInputFile(
                file_path=image_file, filename="test.png", mime_type="image/png"
            ),
            "text-src": TaskInputFile(
                file_path=text_file, filename="test.txt", mime_type="text/plain"
            ),
        }

        result = await scheduler.run(
            self._vlm_wf(),
            node_executor=_make_executor(capture=captured),
            run_id="vlm-multi",
            input_bindings=bindings,
        )

        assert "model-1" in result.completed
        assert "model-1" in captured

        vlm_inputs = captured["model-1"]
        assert "image" in vlm_inputs
        assert "text" in vlm_inputs
        assert vlm_inputs["image"].binary
        assert vlm_inputs["text"].text == "sample text input"

    @pytest.mark.asyncio()
    async def test_vlm_resolved_inputs_in_event(
        self, event_store, registry, storage, image_file, text_file
    ):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        bindings = {
            "img-src": TaskInputFile(
                file_path=image_file, filename="test.png", mime_type="image/png"
            ),
            "text-src": TaskInputFile(
                file_path=text_file, filename="test.txt", mime_type="text/plain"
            ),
        }

        await scheduler.run(
            self._vlm_wf(),
            node_executor=_make_executor(),
            run_id="vlm-resolved",
            input_bindings=bindings,
        )

        events = es.get_events("vlm-resolved")
        vlm_started = [e for e in events if e.node_id == "model-1" and e.event_type == "started"]
        assert len(vlm_started) == 1

        ri = vlm_started[0].resolved_inputs
        assert "image" in ri
        assert "text" in ri
        assert ri["image"].source_node_id == "img-src"
        assert ri["text"].source_node_id == "text-src"


# ---------------------------------------------------------------------------
# 11.4 Branch failure isolation
# ---------------------------------------------------------------------------


class TestBranchFailureIsolation:
    """One engine fails, the other continues unaffected."""

    @staticmethod
    def _parallel_wf() -> WorkflowDefinition:
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

    @pytest.mark.asyncio()
    async def test_failed_node_has_failed_event(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(fail_nodes={"model-1"}),
            run_id="branch-fail",
            input_bindings=_bindings(image_file),
        )

        assert "ocr-1" in result.completed
        assert "model-1" in result.failed

        events = es.get_events("branch-fail")
        failed_events = [e for e in events if e.event_type == "failed"]
        assert any(e.node_id == "model-1" for e in failed_events)

    @pytest.mark.asyncio()
    async def test_healthy_branch_unaffected(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(fail_nodes={"model-1"}),
            run_id="branch-healthy",
            input_bindings=_bindings(image_file),
        )

        assert "upload-1" in result.completed
        assert "ocr-1" in result.completed

        events = es.get_events("branch-healthy")
        ocr_completed = [e for e in events if e.node_id == "ocr-1" and e.event_type == "completed"]
        assert len(ocr_completed) == 1

    @pytest.mark.asyncio()
    async def test_downstream_of_failure_skipped(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        wf = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="upload-1", type="input/image", config={}),
                WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
                WorkflowNode(id="output-1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
                WorkflowConnection(source="ocr-1", target="output-1", target_port="input"),
            ],
        )

        state = await scheduler.run(
            wf,
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="skip-downstream",
            input_bindings=_bindings(image_file),
        )

        events = es.get_events("skip-downstream")
        skipped = [e for e in events if e.event_type == "skipped"]
        assert any(e.node_id == "output-1" for e in skipped)
        assert "output-1" in state.failed
        assert state.failed["output-1"] == "dependency failed"

    @pytest.mark.asyncio()
    async def test_partial_completion_state(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._parallel_wf(),
            node_executor=_make_executor(fail_nodes={"model-1"}),
            run_id="partial-state",
            input_bindings=_bindings(image_file),
        )

        assert "upload-1" in result.completed
        assert "ocr-1" in result.completed
        assert "model-1" in result.failed
        assert "output-1" in result.failed
        assert result.failed["output-1"] == "dependency failed"


# ---------------------------------------------------------------------------
# DAGRunResult status propagation
# ---------------------------------------------------------------------------


class TestDAGRunResultStatuses:
    """Verify DAGRunResult correctly classifies nodes into completed/failed/skipped."""

    @staticmethod
    def _linear_wf() -> WorkflowDefinition:
        return WorkflowDefinition(
            nodes=[
                WorkflowNode(id="upload-1", type="input/image", config={}),
                WorkflowNode(id="ocr-1", type="engine/ocr", config={}),
                WorkflowNode(id="output-1", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="upload-1", target="ocr-1", target_port="images"),
                WorkflowConnection(source="ocr-1", target="output-1", target_port="input"),
            ],
        )

    @pytest.mark.asyncio()
    async def test_all_completed_result(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._linear_wf(),
            node_executor=_make_executor(),
            run_id="result-ok",
            input_bindings=_bindings(image_file),
        )

        assert len(result.completed) == 3
        assert len(result.failed) == 0
        assert len(result.skipped) == 0

    @pytest.mark.asyncio()
    async def test_failed_node_in_result(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._linear_wf(),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="result-fail",
            input_bindings=_bindings(image_file),
        )

        assert "upload-1" in result.completed
        assert "ocr-1" in result.failed
        assert "ocr-1" not in result.completed

    @pytest.mark.asyncio()
    async def test_skipped_downstream_in_result(self, event_store, registry, storage, image_file):
        es, _ = event_store
        scheduler = DAGScheduler(event_store=es, node_registry=registry, storage=storage)

        result = await scheduler.run(
            self._linear_wf(),
            node_executor=_make_executor(fail_nodes={"ocr-1"}),
            run_id="result-skip",
            input_bindings=_bindings(image_file),
        )

        assert "output-1" in result.failed
        assert result.failed["output-1"] == "dependency failed"
        assert "output-1" not in result.completed
