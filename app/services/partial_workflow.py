from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowTestRequest(BaseModel):
    target_node_id: str
    include_downstream: bool = False
    input_bindings: dict[str, dict] = Field(default_factory=dict)


def compute_execution_scope(
    nodes: list, connections: list, target_node_id: str, include_downstream: bool
) -> set[str]:
    node_ids = {n.id for n in nodes}
    if target_node_id not in node_ids:
        return set()

    deps: dict[str, set[str]] = {n.id: set() for n in nodes}
    downstream: dict[str, set[str]] = {n.id: set() for n in nodes}
    for conn in connections:
        if conn.source in deps and conn.target in deps:
            deps[conn.target].add(conn.source)
            downstream[conn.source].add(conn.target)

    scope = {target_node_id}
    queue = [target_node_id]
    while queue:
        nid = queue.pop()
        for dep in deps.get(nid, set()):
            if dep not in scope:
                scope.add(dep)
                queue.append(dep)

    if include_downstream:
        queue = [target_node_id]
        while queue:
            nid = queue.pop()
            for child in downstream.get(nid, set()):
                if child not in scope:
                    scope.add(child)
                    queue.append(child)

    return scope


def compute_ancestor_closure(
    nodes: list, connections: list, target_node_id: str, include_target: bool = True
) -> set[str]:
    """Return the set of ancestor node IDs for target_node_id.

    When include_target is True, the target node itself is included in the
    returned set. When False, only upstream ancestors are returned.
    """
    node_ids = {n.id for n in nodes}
    if target_node_id not in node_ids:
        return set()

    deps: dict[str, set[str]] = {n.id: set() for n in nodes}
    for conn in connections:
        if conn.source in deps and conn.target in deps:
            deps[conn.target].add(conn.source)

    ancestors: set[str] = set()
    queue = list(deps.get(target_node_id, set()))
    while queue:
        nid = queue.pop()
        if nid in ancestors:
            continue
        ancestors.add(nid)
        queue.extend(deps.get(nid, set()))

    if include_target:
        ancestors.add(target_node_id)

    return ancestors
