from __future__ import annotations

import pytest

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services import workflow_utils


def _simple_workflow() -> WorkflowDefinition:
    """A minimal valid workflow: input -> engine -> end/final."""
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Legacy output/* node migration
# ---------------------------------------------------------------------------


def test_normalize_replaces_legacy_output_nodes_with_end_final() -> None:
    """Legacy output/markdown nodes are removed and upstream reconnected to end/final."""
    if not hasattr(workflow_utils, "normalize_workflow_definition_for_ingress"):
        pytest.fail("normalize_workflow_definition_for_ingress is not implemented")

    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="output/markdown", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )

    normalized = workflow_utils.normalize_workflow_definition_for_ingress(definition)

    node_types = {node.id: node.type for node in normalized.nodes}
    # The legacy output/markdown node should have been removed
    assert "output_1" not in node_types
    # A new end/final node should have been added
    end_nodes = [nid for nid, ntype in node_types.items() if ntype == "end/final"]
    assert len(end_nodes) == 1
    end_id = end_nodes[0]
    # The upstream engine should now connect directly to the end node
    assert any(
        connection.source == "engine_1" and connection.target == end_id
        for connection in normalized.connections
    )
    # No legacy output/* nodes remain
    assert all(not n.type.startswith("output/") for n in normalized.nodes)


def test_normalize_removes_multiple_legacy_output_nodes() -> None:
    """Multiple legacy output/* nodes are all removed and their upstreams connected to end/final."""
    if not hasattr(workflow_utils, "normalize_workflow_definition_for_ingress"):
        pytest.fail("normalize_workflow_definition_for_ingress is not implemented")

    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="engine_2", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="output/markdown", config={}),
            WorkflowNode(id="output_2", type="output/plaintext", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="input_1", target="engine_2"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="engine_2", target="output_2"),
        ],
    )

    normalized = workflow_utils.normalize_workflow_definition_for_ingress(definition)

    node_types = {node.id: node.type for node in normalized.nodes}
    # Both legacy output nodes removed
    assert "output_1" not in node_types
    assert "output_2" not in node_types
    # Exactly one end/final created
    end_nodes = [nid for nid, ntype in node_types.items() if ntype == "end/final"]
    assert len(end_nodes) == 1
    end_id = end_nodes[0]
    # Both engines now connect to the single end node
    sources_to_end = {c.source for c in normalized.connections if c.target == end_id}
    assert sources_to_end == {"engine_1", "engine_2"}


# ---------------------------------------------------------------------------
# 2. Missing end/final node — auto-create
# ---------------------------------------------------------------------------


def test_normalize_adds_end_final_when_no_end_node_exists() -> None:
    """When a workflow has no end/final and no output/* nodes, one is created for dangling nodes."""
    if not hasattr(workflow_utils, "normalize_workflow_definition_for_ingress"):
        pytest.fail("normalize_workflow_definition_for_ingress is not implemented")

    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
        ],
    )

    normalized = workflow_utils.normalize_workflow_definition_for_ingress(definition)

    node_types = {node.id: node.type for node in normalized.nodes}
    end_nodes = [nid for nid, ntype in node_types.items() if ntype == "end/final"]
    assert len(end_nodes) == 1
    end_id = end_nodes[0]
    # Dangling engine_1 should now connect to the end node
    assert any(c.source == "engine_1" and c.target == end_id for c in normalized.connections)


# ---------------------------------------------------------------------------
# 3. Already-valid workflow — no changes
# ---------------------------------------------------------------------------


def test_normalize_preserves_already_valid_workflow() -> None:
    """A workflow that already has a single end/final and no output/* nodes is unchanged."""
    if not hasattr(workflow_utils, "normalize_workflow_definition_for_ingress"):
        pytest.fail("normalize_workflow_definition_for_ingress is not implemented")

    original = _simple_workflow()
    normalized = workflow_utils.normalize_workflow_definition_for_ingress(original)

    assert len(normalized.nodes) == len(original.nodes)
    assert len(normalized.connections) == len(original.connections)
    node_ids = {n.id for n in normalized.nodes}
    assert node_ids == {"input_1", "engine_1", "end_1"}


# ---------------------------------------------------------------------------
# 4. Multiple end/final nodes — preserved for validator to reject
# ---------------------------------------------------------------------------


def test_normalize_preserves_multiple_end_final_nodes_for_validator() -> None:
    """Multiple end/final nodes (without any legacy output/*) are kept so the
    validator can emit WORKFLOW_MULTIPLE_END."""
    if not hasattr(workflow_utils, "normalize_workflow_definition_for_ingress"):
        pytest.fail("normalize_workflow_definition_for_ingress is not implemented")

    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/text", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
            WorkflowNode(id="end_2", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
            WorkflowConnection(source="engine_1", target="end_2"),
        ],
    )

    normalized = workflow_utils.normalize_workflow_definition_for_ingress(definition)

    end_ids = [node.id for node in normalized.nodes if node.type == "end/final"]
    # Both end/final nodes are preserved — validator will reject with WORKFLOW_MULTIPLE_END
    assert sorted(end_ids) == ["end_1", "end_2"]
