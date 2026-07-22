from __future__ import annotations

import copy


def migrate_workflow(workflow: dict) -> dict:
    """Migrate workflow JSON: replace engine/vlm nodes with engine/model.

    - Replaces node_type "engine/vlm" with "engine/model"
    - Preserves all config fields (model, prompt, temperature, etc.)
    - Preserves all edge connections (source/target references unchanged)
    - Returns a new dict (does not mutate the input)
    - If no engine/vlm nodes found, returns input unchanged (no-op)
    """
    # Check if migration is needed
    has_vlm = any(node.get("type") == "engine/vlm" for node in workflow.get("nodes", []))
    if not has_vlm:
        return workflow

    result = copy.deepcopy(workflow)
    for node in result.get("nodes", []):
        if node.get("type") == "engine/vlm":
            node["type"] = "engine/model"
    return result
