from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.workflow_store import WorkflowStore

WORKSPACE_ID = "ws_workflow_versions"
OTHER_WORKSPACE_ID = "ws_other"


def _sample_definition(node_suffix: str = "1") -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id=f"input_{node_suffix}", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id=f"engine_{node_suffix}",
                type="engine/text",
                config={"encoding": "utf-8"},
            ),
            WorkflowNode(id=f"output_{node_suffix}", type="output/markdown", config={}),
        ],
        connections=[
            WorkflowConnection(source=f"input_{node_suffix}", target=f"engine_{node_suffix}"),
            WorkflowConnection(source=f"engine_{node_suffix}", target=f"output_{node_suffix}"),
        ],
    )


def test_publish_creates_immutable_version_snapshot() -> None:
    store = WorkflowStore()
    workflow = store.create(
        name="wf",
        description="draft",
        definition=_sample_definition("1"),
        workspace_id=WORKSPACE_ID,
    )

    assert store.get(workflow.id, workspace_id=WORKSPACE_ID) is not None
    assert store.get(workflow.id, workspace_id=OTHER_WORKSPACE_ID) is None
    assert [item.id for item in store.list(workspace_id=WORKSPACE_ID)] == [workflow.id]
    assert store.list(workspace_id=OTHER_WORKSPACE_ID) == []
    assert store.publish(workflow.id, workspace_id=OTHER_WORKSPACE_ID) is None

    published = store.publish(workflow.id, workspace_id=WORKSPACE_ID)

    assert published is not None
    assert published.version == 1
    assert published.status == "published"
    assert published.definition.nodes[1].config["encoding"] == "utf-8"

    assert (
        store.update(
            workflow.id,
            definition=_sample_definition("2"),
            workspace_id=OTHER_WORKSPACE_ID,
        )
        is None
    )
    updated = store.update(
        workflow.id,
        definition=_sample_definition("2"),
        workspace_id=WORKSPACE_ID,
    )
    assert updated is not None

    assert store.list_versions(workflow.id, workspace_id=OTHER_WORKSPACE_ID) == []
    versions = store.list_versions(workflow.id, workspace_id=WORKSPACE_ID)
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].definition.nodes[1].id == "engine_1"

    assert store.delete(workflow.id, workspace_id=OTHER_WORKSPACE_ID) is False
    assert store.get(workflow.id, workspace_id=WORKSPACE_ID) is not None
    assert store.delete(workflow.id, workspace_id=WORKSPACE_ID) is True
    assert store.get(workflow.id, workspace_id=WORKSPACE_ID) is None


def test_restore_uses_published_version_definition() -> None:
    store = WorkflowStore()
    workflow = store.create(
        name="wf",
        description=None,
        definition=_sample_definition("1"),
        workspace_id=WORKSPACE_ID,
    )
    store.publish(workflow.id, workspace_id=WORKSPACE_ID)
    store.update(
        workflow.id,
        definition=_sample_definition("2"),
        workspace_id=WORKSPACE_ID,
    )

    assert (
        store.restore(
            workflow.id,
            version=1,
            workspace_id=OTHER_WORKSPACE_ID,
        )
        is None
    )

    restored = store.restore(workflow.id, version=1, workspace_id=WORKSPACE_ID)

    assert restored is not None
    assert restored.workspace_id == WORKSPACE_ID
    assert restored.definition.nodes[1].id == "engine_1"
    assert restored.definition.nodes[2].id == "output_1"


def test_restore_creates_new_saved_version_without_mutating_source_versions() -> None:
    store = WorkflowStore()
    workflow = store.create(
        name="Workflow v1",
        description="original description",
        definition=_sample_definition("1"),
        workspace_id=WORKSPACE_ID,
    )

    saved_v2 = store.save(
        workflow_id=workflow.id,
        workflow_key=workflow.workflow_key,
        base_version=workflow.latest_version,
        name="Workflow v2",
        description="draft description",
        definition=_sample_definition("2"),
        workspace_id=WORKSPACE_ID,
    )

    original_versions = store.list_versions(workflow.id, workspace_id=WORKSPACE_ID)
    version_one_snapshot = next(item for item in original_versions if item.version == 1)
    version_two_snapshot = next(item for item in original_versions if item.version == 2)
    version_one_definition_before = version_one_snapshot.definition.model_copy(deep=True)
    version_two_definition_before = version_two_snapshot.definition.model_copy(deep=True)

    restored = store.restore(workflow.id, version=1, workspace_id=WORKSPACE_ID)

    assert restored is not None
    assert restored.id == workflow.id
    assert restored.workflow_key == workflow.workflow_key
    assert restored.workspace_id == WORKSPACE_ID
    assert restored.name == version_one_snapshot.name == "Workflow v1"
    assert restored.description == version_one_snapshot.description == "original description"
    assert restored.definition == version_one_snapshot.definition
    assert restored.definition is not version_one_snapshot.definition
    assert saved_v2.latest_version == 2
    assert restored.latest_version == 3
    assert restored.published_version == saved_v2.published_version is None
    assert len(restored.versions) == 3

    restored.definition.nodes[1].config["encoding"] = "mutated-after-restore"

    persisted_again = store.get(workflow.id, workspace_id=WORKSPACE_ID)
    assert persisted_again is not None
    assert persisted_again.definition.nodes[1].config["encoding"] == "utf-8"

    versions_after_restore = store.list_versions(workflow.id, workspace_id=WORKSPACE_ID)
    assert len(versions_after_restore) == 3
    assert [item.version for item in versions_after_restore] == [3, 2, 1]
    assert (
        next(item for item in versions_after_restore if item.version == 1).definition
        == version_one_definition_before
    )
    assert (
        next(item for item in versions_after_restore if item.version == 2).definition
        == version_two_definition_before
    )
    assert (
        next(item for item in versions_after_restore if item.version == 3).definition
        == version_one_definition_before
    )
