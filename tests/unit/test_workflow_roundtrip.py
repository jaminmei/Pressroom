from __future__ import annotations

from copy import deepcopy

from app.models.workflow import WorkflowDefinition
from app.services.workflow_store import WorkflowStore
from tests.helpers.workflow_persistence_samples import (
    complex_workflow_definition,
    complex_workflow_definition_dict,
    complex_workflow_definition_with_top_level_extras,
    runtime_metadata_keys,
)

WORKSPACE_ID = "ws_roundtrip"


def test_workflow_definition_model_dump_validate_preserves_complex_ordered_config() -> None:
    definition = complex_workflow_definition()

    dumped = definition.model_dump(mode="json")
    revalidated = WorkflowDefinition.model_validate(dumped)

    assert dumped == complex_workflow_definition_dict()
    assert revalidated == definition
    assert revalidated.nodes[2].config["input_bindings"] == [
        {"name": "image", "selector": ["input_1", "binary"]},
        {"name": "first_region_text", "selector": ["layout_1", "structured", "elements"]},
        {"name": "elements", "selector": ["layout_1", "structured", "elements"]},
    ]
    assert revalidated.nodes[3].config["engine_config"]["input_bindings"] == [
        {"name": "item", "selector": ["iter_1", "item"]},
        {"name": "index", "selector": ["iter_1", "index"]},
        {
            "name": "ancestor_elements",
            "selector": ["layout_1", "structured", "elements"],
        },
    ]


def test_in_memory_workflow_store_round_trip_preserves_complex_definition_and_versions() -> None:
    store = WorkflowStore()
    definition_v1 = complex_workflow_definition()
    workflow = store.create(
        name="Complex v1",
        description="initial",
        definition=definition_v1,
        workspace_id=WORKSPACE_ID,
    )

    fetched = store.get(workflow.id, workspace_id=WORKSPACE_ID)
    assert fetched is not None
    assert fetched.definition == definition_v1

    definition_v2_payload = deepcopy(complex_workflow_definition_dict())
    definition_v2_payload["nodes"][2]["config"]["unknown_nested"]["list_order"] = [
        "gamma",
        "beta",
        "alpha",
    ]
    definition_v2_payload["nodes"][3]["config"]["engine_config"]["unknown_nested"]["ordered"] = [
        3,
        2,
        1,
    ]
    definition_v2 = WorkflowDefinition.model_validate(definition_v2_payload)

    saved = store.save(
        workflow_id=workflow.id,
        workflow_key=workflow.workflow_key,
        name="Complex v2",
        description="updated",
        definition=definition_v2,
        base_version=workflow.latest_version,
        workspace_id=WORKSPACE_ID,
    )
    assert saved.latest_version == 2
    assert saved.definition == definition_v2

    version_one = store.get_version(workflow.id, 1, workspace_id=WORKSPACE_ID)
    version_two = store.get_version(workflow.id, 2, workspace_id=WORKSPACE_ID)
    assert version_one is not None
    assert version_two is not None
    assert version_one.definition == definition_v1
    assert version_two.definition == definition_v2
    assert [
        item.version for item in store.list_versions(workflow.id, workspace_id=WORKSPACE_ID)
    ] == [2, 1]

    restored = store.restore(workflow.id, version=1, workspace_id=WORKSPACE_ID)
    assert restored is not None
    assert restored.name == "Complex v1"
    assert restored.description == "initial"
    assert restored.definition == definition_v1
    assert restored.latest_version == 3


def test_workflow_definition_top_level_extras_follow_current_ignore_behavior() -> None:
    definition = WorkflowDefinition.model_validate(
        complex_workflow_definition_with_top_level_extras()
    )

    dumped = definition.model_dump(mode="json")

    assert "top_level_extra" not in dumped
    assert dumped == complex_workflow_definition_dict()


def test_clean_definition_does_not_gain_runtime_metadata_keys() -> None:
    definition = complex_workflow_definition()

    for node in definition.nodes:
        config_keys = set(node.config)
        if node.id == "adaptor_1":
            assert "_binding_source" in config_keys
        elif node.id == "iter_1":
            assert "_iteration_scope" in config_keys
            assert "_iteration_item" not in config_keys
            assert "_iteration_index" not in config_keys

    clean_payload = deepcopy(complex_workflow_definition_dict())
    clean_payload["nodes"][2]["config"].pop("_binding_source")
    clean_payload["nodes"][3]["config"].pop("_iteration_scope")
    clean_payload["nodes"][3]["config"]["engine_config"].pop("_iteration_item")
    clean_payload["nodes"][3]["config"]["engine_config"].pop("_iteration_index")

    clean_definition = WorkflowDefinition.model_validate(clean_payload)
    dumped = clean_definition.model_dump(mode="json")
    for key in runtime_metadata_keys():
        assert key not in str(dumped)
