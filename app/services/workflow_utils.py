"""Shared workflow utility functions.

Extracted from app.api.tasks and app.services.task_orchestrator to eliminate
duplication of BFS traversal, result-building, file-placeholder parsing, and
MIME-type inference logic.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.task import NodeState
    from app.models.workflow import WorkflowDefinition

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode


def resolve_engine_for_output_node(
    workflow: WorkflowDefinition,
    output_node_id: str,
    *,
    node_states: dict[str, NodeState] | None = None,
    fallback_engine: str | None = None,
) -> tuple[str, str]:
    """BFS backwards from *output_node_id* to find the nearest engine node.

    Returns ``(engine_node_id, engine_type)`` or a sensible fallback when no
    engine predecessor is found.

    Parameters
    ----------
    workflow:
        The workflow definition containing nodes and connections.
    output_node_id:
        The output node to trace back from.
    node_states:
        Optional node-state mapping (unused in BFS but kept for call-site
        compatibility with the orchestrator).
    fallback_engine:
        Engine string returned when no engine predecessor is discovered.
        Defaults to ``"ocr"`` when *None*.
    """
    effective_fallback = fallback_engine if fallback_engine is not None else "ocr"
    nodes = {node.id: node for node in workflow.nodes}
    queue = [output_node_id]
    visited = {output_node_id}

    while queue:
        current = queue.pop(0)
        predecessors = [
            connection.source for connection in workflow.connections if connection.target == current
        ]
        for predecessor in predecessors:
            if predecessor in visited:
                continue
            visited.add(predecessor)
            node = nodes.get(predecessor)
            if node is None:
                continue
            if node.type.startswith("engine/"):
                return predecessor, node.type.split("/", 1)[1]
            queue.append(predecessor)

    return "engine_1", effective_fallback


def extract_file_placeholder_index(value: object) -> int | None:
    """Parse ``$file_<N>`` placeholder strings and return the integer index.

    Returns *None* when *value* is not a valid placeholder.
    """
    if not isinstance(value, str):
        return None
    # Accept both strict ``$file_0`` and the regex variant used in tasks.py.
    stripped = value.strip()
    if not stripped.startswith("$file_"):
        return None
    suffix = stripped[len("$file_") :]
    match = re.fullmatch(r"\d+", suffix)
    if match is None:
        return None
    return int(suffix)


def infer_input_node_type(mime_type: str) -> str:
    """Map a MIME type to the corresponding ``input/*`` workflow node type.

    Raises :class:`ValueError` for unsupported MIME types.
    """
    normalized = mime_type.lower()
    if normalized == "application/pdf":
        return "input/pdf"
    if normalized in {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/tif",
    }:
        return "input/image"
    if normalized == "text/html":
        return "input/html"
    if normalized == "text/plain":
        return "input/text"
    raise ValueError(f"Unsupported MIME type: {mime_type}")


def normalize_workflow_definition_for_ingress(
    definition: WorkflowDefinition,
) -> WorkflowDefinition:
    """Normalize legacy aliases and repair the single missing-end case.

    - legacy `output/text` / `output/*` nodes are removed, their upstream
      engines are re-connected directly to the end node
    - a single missing `end/final` node is added when dangling outputs exist
    - existing multiple `end/final` nodes are preserved for the validator to reject
    """

    normalized = definition.model_copy(deep=True)

    # Migrate: remove legacy output nodes, reconnect their upstream to end
    output_node_ids = {n.id for n in normalized.nodes if n.type.startswith("output/")}
    if output_node_ids:
        # Build upstream map: for each output node, find what connects to it
        upstream_of_output: dict[str, str] = {}
        for conn in normalized.connections:
            if conn.target in output_node_ids:
                upstream_of_output[conn.target] = conn.source

        # Remove output nodes
        normalized.nodes = [n for n in normalized.nodes if n.id not in output_node_ids]

        # Remove connections to/from output nodes
        normalized.connections = [
            c
            for c in normalized.connections
            if c.source not in output_node_ids and c.target not in output_node_ids
        ]

        # Find or create end node
        end_nodes = [n for n in normalized.nodes if n.type == "end/final"]
        if not end_nodes:
            existing_ids = {n.id for n in normalized.nodes}
            end_id = "end_1"
            suffix = 1
            while end_id in existing_ids:
                suffix += 1
                end_id = f"end_{suffix}"
            end_node = WorkflowNode(id=end_id, type="end/final", config={})
            normalized.nodes.append(end_node)
        else:
            end_node = end_nodes[0]

        # Reconnect upstream engines directly to end node
        {c.target for c in normalized.connections if c.source == end_node.id}
        already_connected_to_end = {
            c.source for c in normalized.connections if c.target == end_node.id
        }
        for _output_id, upstream_id in upstream_of_output.items():
            if upstream_id not in already_connected_to_end:
                normalized.connections.append(
                    WorkflowConnection(source=upstream_id, target=end_node.id)
                )

    # Also handle the case where there's no end node and no output nodes existed
    end_nodes = [n for n in normalized.nodes if n.type == "end/final"]
    if not end_nodes:
        # Find dangling nodes (nodes with no downstream connections)
        sources_with_downstream = {c.source for c in normalized.connections}
        dangling = [
            n
            for n in normalized.nodes
            if n.id not in sources_with_downstream and n.type != "end/final"
        ]
        if not dangling:
            return normalized

        existing_ids = {n.id for n in normalized.nodes}
        end_id = "end_1"
        suffix = 1
        while end_id in existing_ids:
            suffix += 1
            end_id = f"end_{suffix}"

        normalized.nodes.append(WorkflowNode(id=end_id, type="end/final", config={}))
        for node in dangling:
            normalized.connections.append(WorkflowConnection(source=node.id, target=end_id))

    return normalized
