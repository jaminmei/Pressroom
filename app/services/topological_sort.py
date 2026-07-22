from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.models.workflow import WorkflowDefinition


class CyclicDependencyError(ValueError):
    """Raised when workflow contains cyclic dependencies."""


@dataclass
class ExecutionPlan:
    total_nodes: int
    execution_order: list[list[str]]
    parallel_groups: int
    estimated_duration_seconds: int | None = None


def topological_sort(definition: WorkflowDefinition) -> list[list[str]]:
    node_ids = [node.id for node in definition.nodes]
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    in_degree: dict[str, int] = {node_id: 0 for node_id in node_ids}

    for connection in definition.connections:
        if connection.source not in adjacency or connection.target not in in_degree:
            continue
        adjacency[connection.source].append(connection.target)
        in_degree[connection.target] += 1

    queue = deque(sorted(node_id for node_id in node_ids if in_degree[node_id] == 0))
    execution_order: list[list[str]] = []
    visited = 0

    while queue:
        layer_size = len(queue)
        layer_nodes = sorted(queue.popleft() for _ in range(layer_size))
        layer: list[str] = []
        next_nodes: list[str] = []

        for current in layer_nodes:
            layer.append(current)
            visited += 1

            for target in adjacency[current]:
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    next_nodes.append(target)

        execution_order.append(layer)
        for node_id in sorted(next_nodes):
            queue.append(node_id)

    if visited != len(node_ids):
        raise CyclicDependencyError("Workflow contains cyclic dependencies")

    return execution_order


def build_execution_plan(definition: WorkflowDefinition) -> ExecutionPlan:
    execution_order = topological_sort(definition)
    parallel_groups = sum(1 for layer in execution_order if len(layer) > 1)

    return ExecutionPlan(
        total_nodes=len(definition.nodes),
        execution_order=execution_order,
        parallel_groups=parallel_groups,
        estimated_duration_seconds=None,
    )
