"""Workflow DAG and input hashing for cache-key derivation."""

from __future__ import annotations

import hashlib
import json


def compute_dag_hash(
    nodes: list[dict],
    edges: list[dict],
    node_configs: dict[str, dict],
) -> str:
    """Compute a deterministic hash of the workflow DAG structure.

    Excludes nodes of type ``input/*`` and ``end/final`` so that the hash
    only reflects the processing topology and configuration.

    Args:
        nodes: Each dict must have ``id`` (str) and ``type`` (str).
        edges: Each dict must have ``source`` (str) and ``target`` (str),
            and may have ``sourceHandle`` (str | None) and
            ``targetHandle`` (str | None).
        node_configs: Mapping of node id to its configuration dict.

    Returns:
        SHA-256 hex digest of the canonical DAG representation.
    """

    def _is_excluded(node_type: str) -> bool:
        return node_type.startswith("input/") or node_type == "end/final"

    # Step 1-2: Filter and compute composite keys for non-excluded nodes.
    node_composites: dict[str, tuple[str, str]] = {}
    for node in nodes:
        if _is_excluded(node["type"]):
            continue
        config_json = json.dumps(
            node_configs.get(node["id"], {}),
            sort_keys=True,
            ensure_ascii=False,
        )
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()
        node_composites[node["id"]] = (node["type"], config_hash)

    # Step 3-4: Sort by composite key and build canonical node list.
    sorted_nodes = [
        {"type": ctype, "config_hash": chash}
        for _, (ctype, chash) in sorted(node_composites.items(), key=lambda item: item[1])
    ]

    # Step 5-6: Build edge entries for non-excluded connections, then sort.
    edge_entries: list[dict] = []
    for edge in edges:
        src_id = edge["source"]
        tgt_id = edge["target"]
        if src_id not in node_composites or tgt_id not in node_composites:
            continue
        src_composite = node_composites[src_id]
        tgt_composite = node_composites[tgt_id]
        edge_entries.append(
            {
                "source_key": src_composite,
                "target_key": tgt_composite,
                "source_handle": edge.get("sourceHandle"),
                "target_handle": edge.get("targetHandle"),
            }
        )
    sorted_edges = sorted(
        edge_entries,
        key=lambda e: (e["source_key"], e["target_key"], e["source_handle"], e["target_handle"]),
    )

    # Step 7-8: Canonical JSON then SHA-256.
    canonical = json.dumps(
        {"nodes": sorted_nodes, "edges": sorted_edges},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_workflow_hash(
    dag_hash: str,
    input_files: list[dict],
) -> str:
    """Compute a deterministic hash combining the DAG and input files.

    Args:
        dag_hash: Output of :func:`compute_dag_hash`.
        input_files: Each dict must have ``name`` (str) and ``size`` (int),
            and may have ``content_hash`` (str | None).

    Returns:
        SHA-256 hex digest of the canonical workflow representation.
    """
    sorted_inputs = sorted(input_files, key=lambda f: (f["name"], f["size"]))
    canonical = json.dumps(
        {"dag_hash": dag_hash, "inputs": sorted_inputs},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
