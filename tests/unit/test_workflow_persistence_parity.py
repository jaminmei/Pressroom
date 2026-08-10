from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.workflow import WorkflowActor, WorkflowDefinition
from app.services.database_workflow_store import (
    DatabaseWorkflowStore,
)
from app.services.database_workflow_store import (
    WorkflowVersionConflictError as DatabaseWorkflowVersionConflictError,
)
from app.services.workflow_store import WorkflowStore, WorkflowVersionConflictError
from app.utils.workflow_hash import compute_dag_hash
from tests.helpers.workflow_persistence_samples import (
    cloned_complex_definition_dict,
    complex_workflow_definition,
)

WORKSPACE_ID = "ws_persistence_parity"
ACTOR = WorkflowActor(user_id="usr_1", email="owner@example.com", name="Owner")


def _definition_hash(definition: WorkflowDefinition) -> str:
    return compute_dag_hash(
        [{"id": node.id, "type": node.type} for node in definition.nodes],
        [
            {
                "source": connection.source,
                "target": connection.target,
                "sourceHandle": connection.source_port,
                "targetHandle": connection.target_port,
            }
            for connection in definition.connections
        ],
        {node.id: deepcopy(node.config) for node in definition.nodes},
    )


@pytest.fixture(params=["memory", "database"])
def workflow_store_under_test(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[tuple[object, type[Exception]]]:
    if request.param == "memory":
        yield WorkflowStore(), WorkflowVersionConflictError
        return

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-store.sqlite3'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield (
            DatabaseWorkflowStore(session_factory=session_factory),
            DatabaseWorkflowVersionConflictError,
        )
    finally:
        engine.dispose()


def test_store_round_trip_restore_and_snapshot_immutability(
    workflow_store_under_test: tuple[object, type[Exception]],
) -> None:
    store, _conflict_error = workflow_store_under_test
    definition_v1 = complex_workflow_definition()
    workflow = store.create(
        name="Complex v1",
        description="original",
        definition=definition_v1,
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )

    payload_v2 = cloned_complex_definition_dict()
    payload_v2["nodes"][3]["config"]["engine_config"]["unknown_nested"]["ordered"] = [3, 2, 1]
    definition_v2 = WorkflowDefinition.model_validate(payload_v2)
    saved = store.save(
        workflow_id=workflow.id,
        workflow_key=workflow.workflow_key,
        name="Complex v2",
        description="draft",
        definition=definition_v2,
        base_version=workflow.latest_version,
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )

    restored = store.restore(workflow.id, version=1, actor=ACTOR, workspace_id=WORKSPACE_ID)
    assert restored is not None
    assert restored.name == "Complex v1"
    assert restored.description == "original"
    assert restored.definition == definition_v1
    assert restored.latest_version == saved.latest_version == 2
    assert restored.published_version == saved.published_version is None

    version_one = store.get_version(workflow.id, 1, workspace_id=WORKSPACE_ID)
    version_two = store.get_version(workflow.id, 2, workspace_id=WORKSPACE_ID)
    assert version_one is not None
    assert version_two is not None
    assert version_one.definition == definition_v1
    assert version_two.definition == definition_v2

    version_one.definition.nodes[1].config["selected_types"] = ["mutated"]
    fetched_again = store.get_version(workflow.id, 1, workspace_id=WORKSPACE_ID)
    assert fetched_again is not None
    assert fetched_again.definition == definition_v1

    restored.definition.nodes[1].config["selected_types"] = ["changed-after-restore"]
    persisted = store.get(workflow.id, workspace_id=WORKSPACE_ID)
    assert persisted is not None
    assert persisted.definition == definition_v1


def test_store_publish_version_helpers_and_conflict_parity(
    workflow_store_under_test: tuple[object, type[Exception]],
) -> None:
    store, conflict_error = workflow_store_under_test
    definition_v1 = complex_workflow_definition()
    dag_hash_v1 = _definition_hash(definition_v1)

    published = store.publish_new_workflow(
        name="Published",
        description="v1",
        definition=definition_v1,
        dag_hash=dag_hash_v1,
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )
    assert published.latest_version == 1
    assert published.published_version == 1
    assert store.find_duplicate_dag_hash(published.id, dag_hash_v1, workspace_id=WORKSPACE_ID) == 1

    payload_v2 = cloned_complex_definition_dict()
    payload_v2["nodes"][2]["config"]["unknown_nested"]["list_order"] = [
        "gamma",
        "beta",
        "alpha",
    ]
    definition_v2 = WorkflowDefinition.model_validate(payload_v2)
    dag_hash_v2 = _definition_hash(definition_v2)

    with pytest.raises(conflict_error):
        store.publish_next_version(
            published.id,
            name="Published stale",
            description="stale",
            definition=definition_v2,
            dag_hash=dag_hash_v2,
            base_version=99,
            actor=ACTOR,
            workspace_id=WORKSPACE_ID,
        )

    republished = store.publish_next_version(
        published.id,
        name="Published v2",
        description="v2",
        definition=definition_v2,
        dag_hash=dag_hash_v2,
        base_version=1,
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )
    assert republished.latest_version == 2
    assert republished.published_version == 2
    assert store.find_duplicate_dag_hash(published.id, dag_hash_v2, workspace_id=WORKSPACE_ID) == 2

    published_v1 = store.get_version(published.id, 1, workspace_id=WORKSPACE_ID)
    published_v2 = store.get_version(published.id, 2, workspace_id=WORKSPACE_ID)
    assert published_v1 is not None
    assert published_v2 is not None
    assert published_v1.status == "published"
    assert published_v1.dag_hash == dag_hash_v1
    assert published_v2.status == "published"
    assert published_v2.dag_hash == dag_hash_v2


def test_store_lists_versions_newest_first_for_parity(
    workflow_store_under_test: tuple[object, type[Exception]],
) -> None:
    store, _conflict_error = workflow_store_under_test
    workflow = store.create(
        name="Version order",
        description="v1",
        definition=complex_workflow_definition(),
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )

    payload_v2 = cloned_complex_definition_dict()
    payload_v2["nodes"][1]["config"]["selected_types"] = ["body", "table"]
    definition_v2 = WorkflowDefinition.model_validate(payload_v2)
    store.save(
        workflow_id=workflow.id,
        workflow_key=workflow.workflow_key,
        name="Version order v2",
        description="v2",
        definition=definition_v2,
        base_version=workflow.latest_version,
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )

    assert [
        item.version for item in store.list_versions(workflow.id, workspace_id=WORKSPACE_ID)
    ] == [2, 1]


def test_store_rejects_duplicate_caller_supplied_workflow_key_when_creating_new_workflow(
    workflow_store_under_test: tuple[object, type[Exception]],
) -> None:
    store, _conflict_error = workflow_store_under_test
    first = store.save(
        workflow_key="wk_duplicate_public_surface",
        name="First",
        description="first",
        definition=complex_workflow_definition(),
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )

    with pytest.raises(Exception) as exc_info:
        store.save(
            workflow_key="wk_duplicate_public_surface",
            name="Second",
            description="second",
            definition=complex_workflow_definition(),
            actor=ACTOR,
            workspace_id=WORKSPACE_ID,
        )

    expected_error = KeyError if isinstance(store, WorkflowStore) else IntegrityError
    assert exc_info.type is expected_error
    second = store.save(
        name="Generated key",
        description="generated",
        definition=complex_workflow_definition(),
        actor=ACTOR,
        workspace_id=WORKSPACE_ID,
    )
    assert first.workflow_key == "wk_duplicate_public_surface"
    assert second.workflow_key is not None
    assert second.workflow_key not in {first.workflow_key, "wk_duplicate_public_surface"}
