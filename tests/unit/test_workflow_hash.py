"""Tests for workflow_hash utility module."""

from __future__ import annotations

from copy import deepcopy

from app.utils.workflow_hash import compute_dag_hash, compute_workflow_hash
from tests.helpers.workflow_persistence_samples import complex_workflow_definition_dict

# --- Helpers ---


def _make_nodes(*specs: tuple[str, str]) -> list[dict]:
    """Build a node list from (id, type) pairs."""
    return [{"id": nid, "type": ntype} for nid, ntype in specs]


def _make_edges(*specs: tuple[str, str]) -> list[dict]:
    """Build an edge list from (source, target) pairs."""
    return [{"source": s, "target": t} for s, t in specs]


def _make_edges_with_handles(
    *specs: tuple[str, str, str | None, str | None],
) -> list[dict]:
    """Build an edge list with handles from (source, target, src_handle, tgt_handle)."""
    return [
        {"source": s, "target": t, "sourceHandle": sh, "targetHandle": th} for s, t, sh, th in specs
    ]


# --- compute_dag_hash tests ---


class TestComputeDagHash:
    """Tests for compute_dag_hash function."""

    def test_same_topology_different_creation_order_same_hash(self) -> None:
        """Two graphs with identical topology but different node/edge order
        must produce the same hash."""
        nodes_a = _make_nodes(("a", "ocr"), ("b", "vlm"), ("c", "output"))
        edges_a = _make_edges(("a", "b"), ("b", "c"))
        configs_a: dict[str, dict] = {"a": {"lang": "en"}, "b": {}, "c": {}}

        nodes_b = _make_nodes(("c", "output"), ("a", "ocr"), ("b", "vlm"))
        edges_b = _make_edges(("b", "c"), ("a", "b"))
        configs_b: dict[str, dict] = {"c": {}, "a": {"lang": "en"}, "b": {}}

        assert compute_dag_hash(nodes_a, edges_a, configs_a) == compute_dag_hash(
            nodes_b,
            edges_b,
            configs_b,
        )

    def test_config_change_produces_different_hash(self) -> None:
        """Changing a node config must change the hash."""
        nodes = _make_nodes(("a", "ocr"), ("b", "output"))
        edges = _make_edges(("a", "b"))

        hash_before = compute_dag_hash(nodes, edges, {"a": {"lang": "en"}})
        hash_after = compute_dag_hash(nodes, edges, {"a": {"lang": "zh"}})

        assert hash_before != hash_after

    def test_delete_readd_produces_same_hash(self) -> None:
        """Removing a node+edge then adding it back yields the same hash."""
        nodes_full = _make_nodes(("a", "ocr"), ("b", "vlm"), ("c", "output"))
        edges_full = _make_edges(("a", "b"), ("b", "c"))
        configs_full: dict[str, dict] = {"a": {"k": 1}, "b": {"k": 2}, "c": {}}

        nodes_partial = _make_nodes(("a", "ocr"), ("c", "output"))
        edges_partial = _make_edges(("a", "c"))
        configs_partial: dict[str, dict] = {"a": {"k": 1}, "c": {}}

        hash_full = compute_dag_hash(nodes_full, edges_full, configs_full)
        hash_partial = compute_dag_hash(nodes_partial, edges_partial, configs_partial)

        # They differ because topology changed
        assert hash_full != hash_partial

        # Re-add the deleted node — must match original
        nodes_readd = _make_nodes(("b", "vlm"), ("a", "ocr"), ("c", "output"))
        edges_readd = _make_edges(("b", "c"), ("a", "b"))
        configs_readd: dict[str, dict] = {"b": {"k": 2}, "a": {"k": 1}, "c": {}}

        assert compute_dag_hash(nodes_readd, edges_readd, configs_readd) == hash_full

    def test_input_and_end_nodes_excluded(self) -> None:
        """Nodes of type 'input/*' and 'end/final' must not affect the hash."""
        # Graph with input/end nodes
        nodes_with = _make_nodes(
            ("in1", "input/image"),
            ("a", "ocr"),
            ("end1", "end/final"),
        )
        edges_with = _make_edges(("in1", "a"), ("a", "end1"))
        configs_with: dict[str, dict] = {
            "in1": {"ignored": True},
            "a": {"lang": "en"},
            "end1": {},
        }

        # Graph without those nodes (same effective DAG)
        nodes_without = _make_nodes(("a", "ocr"))
        edges_without: list[dict] = []
        configs_without: dict[str, dict] = {"a": {"lang": "en"}}

        assert compute_dag_hash(nodes_with, edges_with, configs_with) == compute_dag_hash(
            nodes_without,
            edges_without,
            configs_without,
        )

    def test_input_end_nodes_do_not_affect_hash(self) -> None:
        """Different config on input/end nodes must not change the hash."""
        nodes = _make_nodes(
            ("in1", "input/image"),
            ("a", "ocr"),
            ("end1", "end/final"),
        )
        edges = _make_edges(("in1", "a"), ("a", "end1"))

        configs_1: dict[str, dict] = {"in1": {"x": 1}, "a": {"lang": "en"}, "end1": {"z": 9}}
        configs_2: dict[str, dict] = {"in1": {"x": 99}, "a": {"lang": "en"}, "end1": {"z": 0}}

        assert compute_dag_hash(nodes, edges, configs_1) == compute_dag_hash(
            nodes,
            edges,
            configs_2,
        )

    def test_edges_between_excluded_nodes_ignored(self) -> None:
        """Edges connecting to excluded nodes must not appear in the hash."""
        nodes = _make_nodes(("in1", "input/image"), ("a", "ocr"), ("end1", "end/final"))
        edges = _make_edges(("in1", "a"), ("a", "end1"))
        configs: dict[str, dict] = {"a": {"lang": "en"}}

        # Both edges touch an excluded node so the effective edge list is empty.
        hash_a = compute_dag_hash(nodes, edges, configs)

        nodes_b = _make_nodes(("a", "ocr"))
        hash_b = compute_dag_hash(nodes_b, [], configs)

        assert hash_a == hash_b

    def test_edges_with_handles(self) -> None:
        """Edge handles are part of the canonical representation."""
        nodes = _make_nodes(("a", "ocr"), ("b", "vlm"))
        configs: dict[str, dict] = {"a": {}, "b": {}}

        edges_plain = _make_edges(("a", "b"))
        edges_with_handles = _make_edges_with_handles(("a", "b", "out1", "in1"))

        assert compute_dag_hash(nodes, edges_plain, configs) != compute_dag_hash(
            nodes,
            edges_with_handles,
            configs,
        )

    def test_dict_key_order_normalized_but_list_order_preserved(self) -> None:
        base = complex_workflow_definition_dict()
        nodes = [{"id": node["id"], "type": node["type"]} for node in base["nodes"]]
        edges = [
            {
                "source": edge["source"],
                "target": edge["target"],
                "targetHandle": edge.get("target_port"),
                "sourceHandle": edge.get("source_port"),
            }
            for edge in base["connections"]
        ]
        configs = {node["id"]: deepcopy(node["config"]) for node in base["nodes"]}

        reordered_dict_configs = deepcopy(configs)
        reordered_dict_configs["layout_1"] = {"selected_types": ["Text", "Table"]}
        reordered_dict_configs["adaptor_1"] = {
            "_binding_source": {"user_authored": True},
            "unknown_nested": {
                "selector_like": ["layout_1", "structured", "elements", "1"],
                "list_order": ["alpha", "beta", "gamma"],
            },
            "input_bindings": deepcopy(configs["adaptor_1"]["input_bindings"]),
            "input_mode": "custom_bindings",
            "code": configs["adaptor_1"]["code"],
        }

        binding_order_changed = deepcopy(configs)
        binding_order_changed["adaptor_1"]["input_bindings"] = list(
            reversed(binding_order_changed["adaptor_1"]["input_bindings"])
        )

        selector_order_changed = deepcopy(configs)
        selector_order_changed["adaptor_1"]["unknown_nested"]["selector_like"] = [
            "structured",
            "layout_1",
            "elements",
            "1",
        ]

        assert compute_dag_hash(nodes, edges, configs) == compute_dag_hash(
            list(reversed(nodes)),
            list(reversed(edges)),
            reordered_dict_configs,
        )
        assert compute_dag_hash(nodes, edges, configs) != compute_dag_hash(
            nodes,
            edges,
            binding_order_changed,
        )
        assert compute_dag_hash(nodes, edges, configs) != compute_dag_hash(
            nodes,
            edges,
            selector_order_changed,
        )

    def test_hash_excludes_runtime_metadata_and_reflects_nested_adaptor_iteration_changes(
        self,
    ) -> None:
        base = complex_workflow_definition_dict()
        nodes = [{"id": node["id"], "type": node["type"]} for node in base["nodes"]]
        edges = [
            {
                "source": edge["source"],
                "target": edge["target"],
                "targetHandle": edge.get("target_port"),
                "sourceHandle": edge.get("source_port"),
            }
            for edge in base["connections"]
        ]
        configs = {node["id"]: deepcopy(node["config"]) for node in base["nodes"]}

        runtime_only_changed = deepcopy(configs)
        runtime_only_changed["input_1"]["runtime_output"] = {
            "_binding_source": {"node_id": "input_1"}
        }
        runtime_only_changed["end_1"]["metadata"] = {"version": 7, "timestamps": [1, 2, 3]}

        adaptor_changed = deepcopy(configs)
        adaptor_changed["adaptor_1"]["code"] = "def main(inputs):\n    return {'text': 'changed'}"

        iteration_changed = deepcopy(configs)
        iteration_changed["iter_1"]["engine_config"]["unknown_nested"]["ordered"] = [9, 8, 7]

        explicit_default_like = deepcopy(configs)
        explicit_default_like["iter_1"]["engine_config"]["extra_default"] = False

        base_hash = compute_dag_hash(nodes, edges, configs)
        assert base_hash == compute_dag_hash(nodes, edges, runtime_only_changed)
        assert base_hash != compute_dag_hash(nodes, edges, adaptor_changed)
        assert base_hash != compute_dag_hash(nodes, edges, iteration_changed)
        assert base_hash != compute_dag_hash(nodes, edges, explicit_default_like)

    def test_empty_graph(self) -> None:
        """Empty graph produces a stable hash."""
        h = compute_dag_hash([], [], {})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length

    def test_returns_sha256_hex(self) -> None:
        """Hash is always a 64-character hex string."""
        nodes = _make_nodes(("a", "ocr"))
        h = compute_dag_hash(nodes, [], {"a": {}})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# --- compute_workflow_hash tests ---


class TestComputeWorkflowHash:
    """Tests for compute_workflow_hash function."""

    def test_same_inputs_same_hash(self) -> None:
        """Same dag_hash and same files in different order produce same hash."""
        dag = "abc123"
        files_a = [
            {"name": "doc.pdf", "size": 1024, "content_hash": "h1"},
            {"name": "img.png", "size": 512, "content_hash": "h2"},
        ]
        files_b = [
            {"name": "img.png", "size": 512, "content_hash": "h2"},
            {"name": "doc.pdf", "size": 1024, "content_hash": "h1"},
        ]

        assert compute_workflow_hash(dag, files_a) == compute_workflow_hash(dag, files_b)

    def test_different_input_files_different_hash(self) -> None:
        """Different input files must produce a different hash."""
        dag = "abc123"
        files_a = [{"name": "doc.pdf", "size": 1024}]
        files_b = [{"name": "other.pdf", "size": 2048}]

        assert compute_workflow_hash(dag, files_a) != compute_workflow_hash(dag, files_b)

    def test_different_dag_hash_different_result(self) -> None:
        """Different dag_hash must produce a different workflow hash."""
        files = [{"name": "doc.pdf", "size": 1024}]

        assert compute_workflow_hash("hash_a", files) != compute_workflow_hash(
            "hash_b",
            files,
        )

    def test_content_hash_included(self) -> None:
        """content_hash field is part of the canonical representation."""
        dag = "abc123"
        files_with = [{"name": "doc.pdf", "size": 1024, "content_hash": "abc"}]
        files_without = [{"name": "doc.pdf", "size": 1024, "content_hash": "xyz"}]

        assert compute_workflow_hash(dag, files_with) != compute_workflow_hash(
            dag,
            files_without,
        )

    def test_empty_inputs(self) -> None:
        """Empty input list still produces a valid hash."""
        h = compute_workflow_hash("abc123", [])
        assert isinstance(h, str)
        assert len(h) == 64

    def test_returns_sha256_hex(self) -> None:
        """Hash is always a 64-character hex string."""
        h = compute_workflow_hash(
            "abc123",
            [{"name": "doc.pdf", "size": 1024}],
        )
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
