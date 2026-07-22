"""DAG-based workflow scheduler with parallel execution, retries, and skip propagation."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, Protocol

from app.models.execution import (
    BinaryRef,
    ErrorInfo,
    ExecutionEvent,
    NodeOutput,
    ResolvedInput,
)
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition
from app.services.event_store import EventStore
from app.services.node_registry import NodeRegistryService
from app.storage.base import StorageAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DAGNode:
    node_id: str
    node_type: str
    config: dict[str, object]
    named_inputs: dict[str, str] = field(default_factory=dict)  # port_name -> upstream_node_id
    dependencies: set[str] = field(default_factory=set)  # all upstream node IDs


@dataclass
class DAG:
    nodes: dict[str, DAGNode] = field(default_factory=dict)
    roots: set[str] = field(default_factory=set)  # nodes with no dependencies
    downstream: dict[str, set[str]] = field(default_factory=dict)  # node_id -> downstream node_ids


@dataclass
class DAGRunResult:
    """Result of a DAG run: completed nodes, failed node errors, and skipped nodes."""

    completed: dict[str, NodeOutput]
    failed: dict[str, str]  # node_id -> error message
    skipped: set[str]


# ---------------------------------------------------------------------------
# Node executor protocol
# ---------------------------------------------------------------------------


class NodeExecutor(Protocol):
    async def __call__(self, node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput: ...


# ---------------------------------------------------------------------------
# DAG construction
# ---------------------------------------------------------------------------


def build_dag(workflow: WorkflowDefinition) -> DAG:
    """Build a DAG from a workflow definition.

    For each WorkflowNode, create a DAGNode. For each WorkflowConnection,
    populate ``named_inputs`` mapping ``target_port`` (or ``"default"``) to the
    source node ID. Derive the dependency set, downstream adjacency, and root set.
    """
    nodes: dict[str, DAGNode] = {}
    downstream: dict[str, set[str]] = {}

    # Initialise DAGNodes and downstream buckets.
    for wf_node in workflow.nodes:
        nodes[wf_node.id] = DAGNode(
            node_id=wf_node.id,
            node_type=wf_node.type,
            config=dict(wf_node.config),
        )
        downstream[wf_node.id] = set()

    # Populate named_inputs, dependencies, and downstream from connections.
    for conn in workflow.connections:
        target = nodes.get(conn.target)
        if target is None:
            continue
        source_id = conn.source
        port_name = conn.target_port or "default"
        target.named_inputs[port_name] = source_id
        target.dependencies.add(source_id)
        downstream.setdefault(source_id, set()).add(conn.target)

    # Identify roots — nodes with zero dependencies.
    roots = {nid for nid, n in nodes.items() if not n.dependencies}

    return DAG(nodes=nodes, roots=roots, downstream=downstream)


# ---------------------------------------------------------------------------
# Port name resolution
# ---------------------------------------------------------------------------


def _resolve_default_ports(dag: DAG, node_registry: NodeRegistryService) -> None:
    """Resolve virtual port names to actual input_port names.

    The frontend uses virtual handle IDs for rendering:
    - ``"default"`` — non-multi-input nodes with no targetHandle
    - ``"primary"`` — multi-input nodes, left/main handle
    - ``"context"`` — multi-input nodes, top/context handle

    These don't correspond to real port names in the registry.  Remap them
    to the actual ``input_ports[].name`` so DAG validation passes.

    Mapping rules:
    - ``"default"`` / ``"primary"`` → first input port
    - ``"context"`` → last input port (typically the text/context port)
    """
    _VIRTUAL_PORTS = {"default", "primary", "context"}

    for node in dag.nodes.values():
        virtual_keys = _VIRTUAL_PORTS & set(node.named_inputs.keys())
        if not virtual_keys:
            continue
        node_def = node_registry.get_node_definition(node.node_type)
        if node_def is None or not node_def.input_ports:
            continue

        for vport in virtual_keys:
            upstream_id = node.named_inputs.pop(vport)
            if vport == "context" and len(node_def.input_ports) > 1:
                real_port = node_def.input_ports[-1].name
            else:
                real_port = node_def.input_ports[0].name
            node.named_inputs[real_port] = upstream_id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_dag(dag: DAG, node_registry: NodeRegistryService) -> list[str]:
    """Return a list of validation error strings (empty means valid).

    Checks:
    1. Cycle detection (DFS-based).
    2. Unknown node types.
    3. Missing required inputs.
    """
    errors: list[str] = []

    # --- 1. Cycle detection via DFS colouring --------------------------------
    WHITE, GRAY, BLACK = 0, 1, 2
    colours: dict[str, int] = {nid: WHITE for nid in dag.nodes}

    def _dfs(node_id: str) -> bool:
        """Returns True if a cycle is found."""
        colours[node_id] = GRAY
        for child in dag.downstream.get(node_id, set()):
            if colours.get(child) == GRAY:
                return True
            if colours.get(child) == WHITE and _dfs(child):
                return True
        colours[node_id] = BLACK
        return False

    for nid in dag.nodes:
        if colours[nid] == WHITE:
            if _dfs(nid):
                errors.append("Workflow contains a cycle")
                break  # one cycle report is enough

    # --- 2. Unknown node types -----------------------------------------------
    for nid, node in dag.nodes.items():
        if node_registry.get_node_definition(node.node_type) is None:
            errors.append(f"Node '{nid}' has unknown type '{node.node_type}'")

    # --- 3. Missing required inputs ------------------------------------------
    for nid, node in dag.nodes.items():
        node_def = node_registry.get_node_definition(node.node_type)
        if node_def is None:
            continue  # already reported as unknown type

        # Collect required port names from input_ports if defined.
        if node_def.input_ports:
            for port in node_def.input_ports:
                if port.required and port.name not in node.named_inputs:
                    errors.append(f"Node '{nid}' is missing required input port '{port.name}'")
        else:
            # Fallback: if input_ports is empty but the node accepts inputs
            # (max_inputs != 0) and there are no named_inputs at all, flag it
            # only when the node is not a root-type (i.e. it has no dependencies
            # and max_inputs > 0 is fine for source nodes).
            if (
                node_def.max_inputs != 0
                and not node.named_inputs
                and node.dependencies  # non-root that expects inputs
            ):
                errors.append(f"Node '{nid}' expects inputs but has no incoming connections")

    return errors


# ---------------------------------------------------------------------------
# Ready-node detection
# ---------------------------------------------------------------------------


def find_ready_nodes(
    dag: DAG,
    completed: set[str],
    running: set[str],
    failed: set[str] | None = None,
) -> list[DAGNode]:
    """Return nodes whose dependencies are all completed, sorted by node_id."""
    _failed = failed or set()
    ready: list[DAGNode] = []
    for nid, node in dag.nodes.items():
        if nid in completed or nid in running or nid in _failed:
            continue
        if node.dependencies <= completed:
            ready.append(node)
    ready.sort(key=lambda n: n.node_id)
    return ready


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------


def resolve_inputs(
    node: DAGNode,
    state: dict[str, NodeOutput],
) -> dict[str, NodeOutput]:
    """Build ``{port_name: upstream_output}`` from ``node.named_inputs``."""
    return {port: state[upstream_id] for port, upstream_id in node.named_inputs.items()}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class _SkipMarker:
    """Sentinel indicating the node should be skipped."""


def _downstream_closure(dag: DAG, start_nodes: set[str]) -> set[str]:
    """Return *start_nodes* plus all nodes reachable via downstream edges (BFS)."""
    scope = set(start_nodes)
    queue = list(start_nodes)
    while queue:
        current = queue.pop(0)
        for child in dag.downstream.get(current, set()):
            if child not in scope:
                scope.add(child)
                queue.append(child)
    return scope


class DAGScheduler:
    """Async DAG scheduler with skip propagation and event sourcing."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        node_registry: NodeRegistryService,
        storage: StorageAdapter,
    ) -> None:
        self._event_store = event_store
        self._node_registry = node_registry
        self._storage = storage

    def _next_sequence(self, run_id: str) -> int:
        """Return the next sequence number after the highest existing event."""
        max_seq = self._event_store.get_max_sequence(run_id)
        return 0 if max_seq is None else max_seq + 1

    # -- public API -----------------------------------------------------------

    async def run(
        self,
        workflow: WorkflowDefinition,
        *,
        node_executor: NodeExecutor,
        run_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        input_bindings: dict[str, TaskInputFile] | None = None,
        start_nodes: set[str] | None = None,
    ) -> DAGRunResult:
        """Execute a workflow DAG and return the final computed state.

        Parameters
        ----------
        workflow:
            The workflow definition to execute.
        node_executor:
            Callable that executes a single node and returns its output.
        run_id:
            Optional run identifier.  A new UUID is generated if not provided.
        cancel_check:
            Optional callback polled between iterations.  When it returns
            ``True`` the dispatch loop breaks and remaining pending nodes are
            marked skipped.
        input_bindings:
            Optional map of node ID to TaskInputFile for resolving
            placeholder file references (e.g. ``$file_0``) in input nodes.
        start_nodes:
            Optional set of node IDs to re-execute.  When provided, completed
            state for nodes *not* in the rerun scope is pre-filled from the
            event store so that only ``start_nodes`` and their downstream
            are dispatched.  When ``None`` (default), all nodes are executed
            from scratch.
        """
        # 1. Build DAG.
        dag = build_dag(workflow)

        # 1b. Resolve "default" port names to actual input_port names.
        _resolve_default_ports(dag, self._node_registry)

        # 2. Validate.
        errors = validate_dag(dag, self._node_registry)
        if errors:
            raise ValueError("Workflow validation failed: " + "; ".join(errors))

        # 3. Run ID.
        if run_id is None:
            run_id = uuid.uuid4().hex

        # 4. Initialise state — pre-fill from event store when partial execution.
        rerun_scope: set[str] | None
        completed_state: dict[str, NodeOutput]
        completed: set[str]
        seq: int
        if start_nodes is not None:
            rerun_scope = _downstream_closure(dag, start_nodes)
            completed_state = self._event_store.compute_state(run_id)
            completed = set(completed_state.keys())
            seq = self._next_sequence(run_id)
        else:
            rerun_scope = None  # means: all nodes are in scope
            completed_state = {}
            completed = set()
            seq = 0

        # 5. Track failed nodes (for skip propagation).
        failed: set[str] = set()
        failed_errors: dict[str, str] = {}  # node_id -> error message

        running: set[str] = set()

        # -- main loop --------------------------------------------------------
        while True:
            # Check for external cancellation.
            if cancel_check is not None and cancel_check():
                pending = {
                    nid
                    for nid in dag.nodes
                    if nid not in completed and nid not in running and nid not in failed
                }
                for nid in pending:
                    self._append_skipped_event(dag, nid, run_id, seq, "cancelled")
                    failed.add(nid)
                    failed_errors[nid] = "cancelled"
                    seq += 1
                break

            # a. Find ready nodes.
            ready = find_ready_nodes(dag, completed, running, failed)

            # a2. When partial execution, only dispatch nodes in rerun_scope.
            if rerun_scope is not None:
                ready = [n for n in ready if n.node_id in rerun_scope]
                # Nodes outside scope that are "ready" but not in scope —
                # treat them as completed (they already have pre-filled state).
                out_of_scope_ready = [
                    n
                    for n in find_ready_nodes(dag, completed, running, failed)
                    if n.node_id not in rerun_scope and n.node_id not in completed
                ]
                for n in out_of_scope_ready:
                    completed.add(n.node_id)

            if not ready:
                # b. Check for deadlock: are there still pending nodes?
                pending = {
                    nid
                    for nid in dag.nodes
                    if nid not in completed and nid not in running and nid not in failed
                }
                if not pending:
                    break  # all nodes resolved

                # Deadlock: check if all pending nodes have at least one failed
                # dependency (in which case they will never become ready).
                all_blocked_by_failure = all(
                    bool(node.dependencies & failed) for node in (dag.nodes[nid] for nid in pending)
                )
                if all_blocked_by_failure:
                    # Mark all pending nodes as skipped and finish.
                    for nid in pending:
                        self._append_skipped_event(dag, nid, run_id, seq, "dependency failed")
                        failed.add(nid)
                        failed_errors[nid] = "dependency failed"
                        seq += 1
                    break

                # If nothing is running and nothing is ready, remaining nodes
                # are transitively blocked (e.g. end_node depends on a node
                # whose direct dependency failed). Mark them as skipped.
                if not running:
                    for nid in pending:
                        self._append_skipped_event(
                            dag, nid, run_id, seq, "dependency failed (transitive)"
                        )
                        failed.add(nid)
                        failed_errors[nid] = "dependency failed (transitive)"
                        seq += 1
                    break

                # Otherwise wait for running tasks to complete.
                await asyncio.sleep(0.05)
                continue

            # c. Dispatch ready nodes in parallel.
            logger.info(
                "DAG dispatching %d ready nodes: %s", len(ready), [n.node_id for n in ready]
            )
            tasks: list[asyncio.Task[NodeOutput | _SkipMarker]] = []
            task_node_ids: list[str] = []
            for node in ready:
                running.add(node.node_id)

                # Check if any dependency has failed — if so, skip immediately.
                if node.dependencies & failed:
                    tasks.append(asyncio.create_task(self._make_skip_marker()))
                    task_node_ids.append(node.node_id)
                    continue

                tasks.append(
                    asyncio.create_task(
                        self._execute_node(
                            node=node,
                            state=completed_state,
                            executor=node_executor,
                            run_id=run_id,
                            seq_start=seq,
                            input_bindings=input_bindings,
                        )
                    )
                )
                task_node_ids.append(node.node_id)

            # Advance seq by the number of dispatched nodes (each dispatch
            # consumes at least one "started" event).
            seq += len(ready)

            # Await all tasks (return_exceptions ensures isolation).
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # d. Process results.
            logger.info(
                "DAG results for run %s: %s",
                run_id,
                [(task_node_ids[i], type(r).__name__) for i, r in enumerate(results)],
            )
            events_flushed = 0
            for idx, result in enumerate(results):
                nid = task_node_ids[idx]
                node = dag.nodes[nid]
                running.discard(nid)

                if isinstance(result, _SkipMarker):
                    # Skipped due to failed dependency.
                    failed.add(nid)
                    failed_errors[nid] = "dependency failed"
                    self._append_skipped_event(
                        dag, nid, run_id, seq + events_flushed, "dependency failed"
                    )
                    events_flushed += 1
                    continue

                if isinstance(result, BaseException):
                    # Execution raised unexpectedly (should not normally happen
                    # because _execute_node catches internally, but guard anyway).
                    error_info = ErrorInfo(
                        type=type(result).__name__,
                        message=str(result),
                    )
                    self._append_event(
                        run_id=run_id,
                        node=node,
                        event_type="failed",
                        sequence=seq + events_flushed,
                        error=error_info,
                    )
                    events_flushed += 1
                    failed.add(nid)
                    failed_errors[nid] = str(result)
                    continue

                # Success path — result is NodeOutput.
                completed.add(nid)
                completed_state[nid] = result
                events_flushed += 1  # _execute_node already emitted started+completed events

            seq += events_flushed

            # e. Skip propagation: nodes whose dependencies include a failed
        #    node will be caught on the next iteration's ready-check.

        skipped = {nid for nid in dag.nodes if nid not in completed and nid not in failed}
        return DAGRunResult(
            completed=completed_state,
            failed=failed_errors,
            skipped=skipped,
        )

    # -- internals ------------------------------------------------------------

    async def _execute_node(
        self,
        *,
        node: DAGNode,
        state: dict[str, NodeOutput],
        executor: NodeExecutor,
        run_id: str,
        seq_start: int,
        input_bindings: dict[str, TaskInputFile] | None = None,
    ) -> NodeOutput:
        """Execute a single node.

        Routes input/end nodes to built-in handlers.
        Only engine/processor nodes go through the *executor* callback.
        Emits ``started`` / ``completed`` / ``failed`` events.
        """
        inputs = resolve_inputs(node, state)
        resolved_inputs = self._build_resolved_inputs(node, run_id)

        # Emit "started" event.
        self._append_event(
            run_id=run_id,
            node=node,
            event_type="started",
            sequence=seq_start,
            resolved_inputs=resolved_inputs,
        )

        try:
            if node.node_type.startswith("input/"):
                output = await self._execute_input_node(node, run_id, input_bindings)
            elif node.node_type == "end/final":
                output = await self._execute_end_node(node, inputs)
            elif node.node_type == "processor/document_to_image":
                output = await self._execute_document_to_image_processor(node, inputs, run_id)
            else:
                output = await executor(node, inputs)
                # Success — emit "completed" event.
                self._append_event(
                    run_id=run_id,
                    node=node,
                    event_type="completed",
                    sequence=seq_start + 1,
                    output=output,
                )
                return output
        except Exception as exc:
            error_info = ErrorInfo(
                type=type(exc).__name__,
                message=str(exc),
            )
            self._append_event(
                run_id=run_id,
                node=node,
                event_type="failed",
                sequence=seq_start + 1,
                error=error_info,
            )
            raise

        # Success — emit "completed" event.
        self._append_event(
            run_id=run_id,
            node=node,
            event_type="completed",
            sequence=seq_start + 1,
            output=output,
        )
        return output

    # -- event helpers --------------------------------------------------------

    @staticmethod
    def _build_resolved_inputs(node: DAGNode, run_id: str) -> dict[str, ResolvedInput]:
        """Build resolved_inputs map for event emission."""
        resolved: dict[str, ResolvedInput] = {}
        for port_name, upstream_id in node.named_inputs.items():
            resolved[port_name] = ResolvedInput(
                name=port_name,
                source_node_id=upstream_id,
                source_event_id=f"{run_id}:{upstream_id}",
            )
        return resolved

    # -- built-in node executors -----------------------------------------------

    async def _execute_input_node(
        self,
        node: DAGNode,
        run_id: str,
        input_bindings: dict[str, TaskInputFile] | None = None,
    ) -> NodeOutput:
        """Read file and produce NodeOutput. Runs in the event loop (non-blocking)."""
        file_path: str | None = None

        # Prefer input_bindings (real file path) over config (may be placeholder).
        if input_bindings:
            binding = input_bindings.get(node.node_id)
            if binding:
                file_path = binding.file_path

        if not file_path:
            file_path = str(node.config.get("file", ""))

        if not file_path or not os.path.isfile(file_path):
            raise ValueError(f"Input file not found: {file_path}")

        filename = os.path.basename(file_path)
        size_bytes = os.path.getsize(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        if node.node_type == "input/text":
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, self._read_text_file, file_path)
            return NodeOutput(
                text=text,
                metadata={"filename": filename, "mime_type": mime_type, "size_bytes": size_bytes},
            )

        # input/pdf, input/image — binary ref pass-through
        return NodeOutput(
            binary=[BinaryRef(ref=file_path, mime_type=mime_type, size_bytes=size_bytes)],
            metadata={"filename": filename, "mime_type": mime_type, "size_bytes": size_bytes},
        )

    @staticmethod
    def _read_text_file(path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    async def _execute_document_to_image_processor(
        self,
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        run_id: str,
    ) -> NodeOutput:
        """Built-in processor: convert document pages to PNG images."""
        from pdf2image import convert_from_path, pdfinfo_from_path

        # Get PDF path from upstream input
        pdf_path = None
        for port_output in inputs.values():
            if port_output.binary:
                ref = port_output.binary[0].ref
                if ref and os.path.isfile(ref):
                    pdf_path = ref
                    break

        if not pdf_path:
            raise ValueError("No PDF file received from upstream")

        loop = asyncio.get_running_loop()

        pages_str = str(node.config.get("pages", "1") or "1").strip().lower()

        def _pdfinfo() -> dict[str, object]:
            return dict(pdfinfo_from_path(pdf_path))

        info = await loop.run_in_executor(None, _pdfinfo)
        total_pages = int(str(info.get("Pages", 1)))
        page_numbers = self._parse_page_range(pages_str, total_pages)

        if len(page_numbers) > 20:
            raise ValueError(
                f"Cannot convert {len(page_numbers)} pages at once (max 20). "
                "Use a narrower page range."
            )

        binary_refs: list[BinaryRef] = []
        for page_num in page_numbers:

            def _convert_page(page: int = page_num) -> list[Any]:
                return list(
                    convert_from_path(
                        pdf_path,
                        dpi=300,
                        first_page=page,
                        last_page=page,
                    )
                )

            images = await loop.run_in_executor(
                None,
                _convert_page,
            )
            for img in images:
                buf = BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                w, h = img.size

                save_path = await self._storage.save_file(
                    run_id,
                    "images",
                    f"page_{page_num:03d}.png",
                    png_bytes,
                )
                binary_refs.append(
                    BinaryRef(
                        ref=save_path,
                        mime_type="image/png",
                        size_bytes=len(png_bytes),
                        dimensions={"width": w, "height": h},
                    )
                )

        return NodeOutput(
            binary=binary_refs,
            metadata={"pages_converted": len(page_numbers)},
        )

    @staticmethod
    def _parse_page_range(pages_str: str, total_pages: int) -> list[int]:
        """Parse page range string like '1', '1-3', 'all' into page numbers."""
        if pages_str == "all":
            return list(range(1, total_pages + 1))

        # Single page: "1"
        if pages_str.isdigit():
            page = int(pages_str)
            if page < 1 or page > total_pages:
                raise ValueError(f"Page {page} out of range (1-{total_pages})")
            return [page]

        # Range: "1-3"
        if "-" in pages_str:
            parts = pages_str.split("-", 1)
            start, end = int(parts[0]), int(parts[1])
            if start < 1 or end > total_pages or start > end:
                raise ValueError(f"Invalid page range '{pages_str}' for {total_pages}-page PDF")
            return list(range(start, end + 1))

        raise ValueError(f"Invalid pages value: '{pages_str}'. Use '1', '1-3', or 'all'")

    async def _execute_end_node(self, node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
        """Collect all upstream inputs, marking workflow completion."""
        if not inputs:
            return NodeOutput(metadata={"completed_nodes": []})

        # Merge all upstream inputs into a single summary output
        all_text_parts: list[str] = []
        all_binary: list[BinaryRef] = []
        all_structured: dict[str, object] = {}
        completed_nodes: list[str] = []

        for port_name, upstream in inputs.items():
            if upstream.text:
                all_text_parts.append(upstream.text)
            all_binary.extend(upstream.binary)
            if upstream.structured:
                all_structured[port_name] = upstream.structured
            completed_nodes.append(port_name)

        return NodeOutput(
            text="\n\n".join(all_text_parts) if all_text_parts else None,
            binary=all_binary,
            structured=all_structured if all_structured else None,
            metadata={"completed_nodes": completed_nodes},
        )

    def _append_event(
        self,
        *,
        run_id: str,
        node: DAGNode,
        event_type: str,
        sequence: int,
        output: NodeOutput | None = None,
        resolved_inputs: dict[str, ResolvedInput] | None = None,
        error: ErrorInfo | None = None,
    ) -> None:
        event = ExecutionEvent(
            event_id=uuid.uuid4().hex,
            workflow_run_id=run_id,
            node_id=node.node_id,
            node_type=node.node_type,
            event_type=event_type,
            sequence=sequence,
            timestamp=time.time(),
            output=output,
            resolved_inputs=resolved_inputs or {},
            error=error,
        )
        self._event_store.append(event)

    def _append_skipped_event(
        self,
        dag: DAG,
        node_id: str,
        run_id: str,
        sequence: int,
        reason: str,
    ) -> None:
        node = dag.nodes[node_id]
        error_info = ErrorInfo(
            type="Skipped",
            message=f"Node skipped: {reason}",
        )
        self._append_event(
            run_id=run_id,
            node=node,
            event_type="skipped",
            sequence=sequence,
            error=error_info,
        )

    @staticmethod
    async def _make_skip_marker() -> _SkipMarker:
        return _SkipMarker()
