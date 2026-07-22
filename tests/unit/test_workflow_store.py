from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.workflow_store import WorkflowStore

WORKSPACE_ID = "ws_workflow_store"


def _definition(node_suffix: str = "1") -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id=f"input_{node_suffix}", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id=f"engine_{node_suffix}", type="engine/text", config={}),
            WorkflowNode(id=f"output_{node_suffix}", type="output/markdown", config={}),
        ],
        connections=[
            WorkflowConnection(source=f"input_{node_suffix}", target=f"engine_{node_suffix}"),
            WorkflowConnection(source=f"engine_{node_suffix}", target=f"output_{node_suffix}"),
        ],
    )


def test_create_and_get_workflow() -> None:
    store = WorkflowStore()

    created = store.create(
        name="demo",
        description="v1",
        definition=_definition(),
        workspace_id=WORKSPACE_ID,
    )
    fetched = store.get(created.id, workspace_id=WORKSPACE_ID)

    assert created.id.startswith("wf_")
    assert fetched is not None
    assert fetched.name == "demo"
    assert fetched.description == "v1"


def test_update_existing_workflow() -> None:
    store = WorkflowStore()
    created = store.create(
        name="v1",
        description="old",
        definition=_definition(),
        workspace_id=WORKSPACE_ID,
    )

    updated = store.update(
        created.id,
        name="v2",
        description="new",
        definition=_definition("2"),
        workspace_id=WORKSPACE_ID,
    )

    assert updated is not None
    assert updated.id == created.id
    assert updated.name == "v2"
    assert updated.description == "new"
    assert updated.definition.nodes[0].id == "input_2"


def test_update_nonexistent_workflow_returns_none() -> None:
    store = WorkflowStore()

    assert store.update("wf_missing", name="v2", workspace_id=WORKSPACE_ID) is None


def test_delete_workflow() -> None:
    store = WorkflowStore()
    created = store.create(
        name="to-delete",
        description=None,
        definition=_definition(),
        workspace_id=WORKSPACE_ID,
    )

    assert store.delete(created.id, workspace_id=WORKSPACE_ID) is True
    assert store.get(created.id, workspace_id=WORKSPACE_ID) is None
    assert store.delete(created.id, workspace_id=WORKSPACE_ID) is False


def test_list_paginated_sorts_by_updated_at_desc() -> None:
    store = WorkflowStore()
    first = store.create(
        name="a",
        description=None,
        definition=_definition("1"),
        workspace_id=WORKSPACE_ID,
    )
    second = store.create(
        name="b",
        description=None,
        definition=_definition("2"),
        workspace_id=WORKSPACE_ID,
    )
    store.update(first.id, name="a-updated", workspace_id=WORKSPACE_ID)

    page_items, total = store.list_paginated(
        page=1,
        limit=1,
        workspace_id=WORKSPACE_ID,
    )

    assert total == 2
    assert len(page_items) == 1
    assert page_items[0].id == first.id
    assert page_items[0].updated_at >= second.updated_at


def test_list_paginated_by_page() -> None:
    store = WorkflowStore()
    ids = [
        store.create(
            name=f"wf-{index}",
            description=None,
            definition=_definition(str(index)),
            workspace_id=WORKSPACE_ID,
        ).id
        for index in range(5)
    ]

    page_2_items, total = store.list_paginated(
        page=2,
        limit=2,
        sort_by="created_at",
        sort_order="asc",
        workspace_id=WORKSPACE_ID,
    )

    assert total == 5
    assert [item.id for item in page_2_items] == ids[2:4]
