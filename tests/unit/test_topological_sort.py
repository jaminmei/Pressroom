from __future__ import annotations

import pytest

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.topological_sort import (
    CyclicDependencyError,
    build_execution_plan,
    topological_sort,
)


def test_topological_sort_returns_layered_execution_order() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text"),
            WorkflowNode(id="engine_a", type="engine/text"),
            WorkflowNode(id="engine_b", type="engine/text"),
            WorkflowNode(id="output_1", type="end/final"),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_a"),
            WorkflowConnection(source="input_1", target="engine_b"),
            WorkflowConnection(source="engine_a", target="output_1"),
            WorkflowConnection(source="engine_b", target="output_1"),
        ],
    )

    execution_order = topological_sort(definition)

    assert execution_order[0] == ["input_1"]
    assert set(execution_order[1]) == {"engine_a", "engine_b"}
    assert execution_order[2] == ["output_1"]


def test_topological_sort_raises_on_cycle() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="a", type="input/text"),
            WorkflowNode(id="b", type="engine/text"),
        ],
        connections=[
            WorkflowConnection(source="a", target="b"),
            WorkflowConnection(source="b", target="a"),
        ],
    )

    with pytest.raises(CyclicDependencyError):
        topological_sort(definition)


def test_build_execution_plan_sets_parallel_groups() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text"),
            WorkflowNode(id="engine_a", type="engine/text"),
            WorkflowNode(id="engine_b", type="engine/text"),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_a"),
            WorkflowConnection(source="input_1", target="engine_b"),
        ],
    )

    plan = build_execution_plan(definition)

    assert plan.total_nodes == 3
    assert plan.parallel_groups == 1


def test_topological_sort_places_end_node_after_outputs() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text"),
            WorkflowNode(id="engine_1", type="engine/text"),
            WorkflowNode(id="output_1", type="end/final"),
            WorkflowNode(id="end_1", type="end/final"),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
        ],
    )

    execution_order = topological_sort(definition)

    assert execution_order == [["input_1"], ["engine_1"], ["output_1"], ["end_1"]]


def test_topological_sort_canonicalizes_parallel_outputs_before_end_final() -> None:
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text"),
            WorkflowNode(id="engine_1", type="engine/text"),
            WorkflowNode(id="output_b", type="end/final"),
            WorkflowNode(id="output_a", type="end/final"),
            WorkflowNode(id="end_1", type="end/final"),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_b"),
            WorkflowConnection(source="engine_1", target="output_a"),
            WorkflowConnection(source="output_b", target="end_1"),
            WorkflowConnection(source="output_a", target="end_1"),
        ],
    )

    execution_order = topological_sort(definition)

    assert execution_order == [
        ["input_1"],
        ["engine_1"],
        ["output_a", "output_b"],
        ["end_1"],
    ]
