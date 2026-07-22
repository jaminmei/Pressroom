from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.workflow_store import WorkflowStore

WORKSPACE_ID = "ws_workflow_store_listing"


def _sample_definition(node_suffix: str = "1") -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id=f"input_{node_suffix}", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id=f"engine_{node_suffix}",
                type="engine/text",
                config={"encoding": "utf-8"},
            ),
            WorkflowNode(id=f"output_{node_suffix}", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source=f"input_{node_suffix}", target=f"engine_{node_suffix}"),
            WorkflowConnection(source=f"engine_{node_suffix}", target=f"output_{node_suffix}"),
        ],
    )


def _create_workflow(store: WorkflowStore, *, name: str, description: str | None) -> None:
    store.create(
        name=name,
        description=description,
        definition=_sample_definition(name.replace("/", "")),
        workspace_id=WORKSPACE_ID,
    )


def test_list_paginated_filters_by_query() -> None:
    store = WorkflowStore()
    _create_workflow(store, name="Alpha Invoice", description="first record")
    _create_workflow(store, name="Beta", description="alpha zone")
    _create_workflow(store, name="Gamma", description="second record")

    workflows, total = store.list_paginated(
        query="  ALPHA  ",
        limit=10,
        workspace_id=WORKSPACE_ID,
    )

    assert total == 2, "total should reflect filtered count even when pagination limits are applied"
    assert {workflow.name for workflow in workflows} == {"Alpha Invoice", "Beta"}


def test_list_paginated_sorts_and_limits() -> None:
    store = WorkflowStore()
    for name in ("charlie", "alpha", "bravo"):
        _create_workflow(store, name=name, description=None)

    workflows, total = store.list_paginated(
        sort_by="name",
        sort_order="asc",
        workspace_id=WORKSPACE_ID,
    )

    assert total == 3
    assert [workflow.name for workflow in workflows] == ["alpha", "bravo", "charlie"]


def test_list_paginated_pagination_total_consistent() -> None:
    store = WorkflowStore()
    for name in ("alpha-1", "alpha-2", "alpha-3", "beta-1"):
        _create_workflow(store, name=name, description=f"desc {name}")

    workflows, total = store.list_paginated(
        query="alpha",
        sort_by="name",
        sort_order="asc",
        limit=1,
        page=2,
        workspace_id=WORKSPACE_ID,
    )

    assert total == 3
    assert len(workflows) == 1
    assert workflows[0].name == "alpha-2"
