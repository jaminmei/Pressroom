"""Deterministic workspace-scoped runtime fixtures for integration tests."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Final

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.models.db.ground_truth import GroundTruth
from app.models.db.test_document import TestDocument
from app.models.db.test_set import TestSet
from app.models.db.workflow_record import WorkflowRecord
from app.models.db.workflow_version_record import WorkflowVersionRecord
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)

ROLES: Final = ("owner", "admin", "editor", "runner", "viewer")


@dataclass(frozen=True, slots=True)
class PublicRuntimeFixture:
    run_id: str
    user_ids: dict[str, str]
    workspace_a_id: str
    workspace_b_id: str
    minimal_workflow_id: str
    queue_workflow_id: str
    dataset_id: str
    document_ids: tuple[str, str]
    ground_truth_ids: tuple[str, str]
    provider_id: str

    def json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass(frozen=True, slots=True)
class RuntimeFixtureContext:
    harness: WorkspaceApiHarness
    owner: TestClient
    users: dict[str, str]
    provider_store: ProviderStore


def _ids(run_id: str) -> dict[str, str]:
    token = re.sub(r"[^a-zA-Z0-9_]", "_", run_id)
    return {
        "minimal_workflow": f"wf_public_runtime_minimal_{token}",
        "queue_workflow": f"wf_public_runtime_queue_{token}",
        "dataset": f"ts_public_runtime_corgi_{token}",
        "document_1": f"doc_public_runtime_corgi_1_{token}",
        "document_2": f"doc_public_runtime_corgi_2_{token}",
        "ground_truth_1": f"gt_public_runtime_corgi_1_{token}",
        "ground_truth_2": f"gt_public_runtime_corgi_2_{token}",
    }


def _definition(*, provider_id: str | None = None) -> dict[str, list[dict[str, object]]]:
    nodes: list[dict[str, object]] = [
        {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
        {"id": "output_1", "type": "output/markdown", "config": {}},
    ]
    connections: list[dict[str, object]] = [{"source": "input_1", "target": "output_1"}]
    if provider_id is not None:
        nodes[1:1] = [
            {
                "id": "queue_retry_1",
                "type": "engine/text",
                "config": {
                    "provider_id": provider_id,
                    "max_retries": 3,
                    "retry_delay_seconds": 5,
                    "cancellation_delay_seconds": 2,
                },
            },
            {
                "id": "queue_transform_1",
                "type": "engine/text",
                "config": {"provider_id": provider_id},
            },
        ]
        connections = [
            {"source": "input_1", "target": "queue_retry_1"},
            {"source": "queue_retry_1", "target": "queue_transform_1"},
            {"source": "queue_transform_1", "target": "output_1"},
        ]
    return {"nodes": nodes, "connections": connections}


def _provider(store: ProviderStore, workspace_id: str, run_id: str) -> str:
    name = f"Public Runtime queue default {run_id}"
    existing = next((item for item in store.list_visible(workspace_id) if item.name == name), None)
    if existing is not None:
        return existing.id
    return store.create_provider(
        ModelProviderCreate(
            name=name,
            provider_type=ProviderType.engine_service,
            engine_category="text",
            base_url="http://text-engine:8000",
            auth_type="none",
            is_default=True,
            scope=ProviderScope.workspace,
            workspace_id=workspace_id,
        )
    ).id


def setup_public_runtime_fixture(
    runtime: RuntimeFixtureContext, run_id: str
) -> PublicRuntimeFixture:
    ids = _ids(run_id)
    with runtime.harness.session_factory() as session:
        workspaces = {
            workspace.name: workspace.id
            for workspace in session.scalars(
                select(Workspace).where(
                    Workspace.name.in_([f"Public Runtime A {run_id}", f"Public Runtime B {run_id}"])
                )
            )
        }
    workspace_a_id = workspaces.get(f"Public Runtime A {run_id}") or create_workspace(
        runtime.owner, name=f"Public Runtime A {run_id}"
    )
    workspace_b_id = workspaces.get(f"Public Runtime B {run_id}") or create_workspace(
        runtime.owner, name=f"Public Runtime B {run_id}"
    )
    for role in ROLES[1:]:
        with runtime.harness.session_factory() as session:
            membership = session.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == workspace_a_id,
                    WorkspaceMember.user_id == runtime.users[role],
                )
            )
        if membership is None:
            add_member(
                runtime.owner,
                workspace_id=workspace_a_id,
                user_id=runtime.users[role],
                role=role,
            )

    provider_id = _provider(runtime.provider_store, workspace_a_id, run_id)
    definitions = {
        ids["minimal_workflow"]: _definition(),
        ids["queue_workflow"]: _definition(provider_id=provider_id),
    }
    with runtime.harness.session_factory() as session:
        for workflow_id, definition in definitions.items():
            session.merge(
                WorkflowRecord(
                    id=workflow_id,
                    workflow_key=f"wk_{workflow_id}",
                    name=f"Public Runtime {workflow_id}",
                    workspace_id=workspace_a_id,
                    current_definition_json=definition,
                    latest_version=1,
                    created_by_user_id=runtime.users["owner"],
                    last_saved_by_user_id=runtime.users["owner"],
                )
            )
            session.merge(
                WorkflowVersionRecord(
                    id=f"wfv_{workflow_id}",
                    workflow_id=workflow_id,
                    version=1,
                    name=f"Public Runtime {workflow_id}",
                    definition_json=definition,
                    created_by_user_id=runtime.users["owner"],
                )
            )
        session.merge(
            TestSet(
                id=ids["dataset"],
                name=f"Public Runtime Corgi graph {run_id}",
                workspace_id=workspace_a_id,
                document_count=2,
            )
        )
        for index in (1, 2):
            document_id = ids[f"document_{index}"]
            session.merge(
                TestDocument(
                    id=document_id,
                    test_set_id=ids["dataset"],
                    filename=f"corgi-{index}.pdf",
                    mime_type="application/pdf",
                    size_bytes=20,
                    storage_path=f"public_runtime/{run_id}/corgi-{index}.pdf",
                    page_count=1,
                )
            )
            session.merge(
                GroundTruth(
                    id=ids[f"ground_truth_{index}"],
                    document_id=document_id,
                    version=1,
                    source="manual_edit",
                    format="markdown",
                    content=f"# Corgi ground truth {index}",
                )
            )
        session.commit()
    return PublicRuntimeFixture(
        run_id=run_id,
        user_ids=runtime.users,
        workspace_a_id=workspace_a_id,
        workspace_b_id=workspace_b_id,
        minimal_workflow_id=ids["minimal_workflow"],
        queue_workflow_id=ids["queue_workflow"],
        dataset_id=ids["dataset"],
        document_ids=(ids["document_1"], ids["document_2"]),
        ground_truth_ids=(ids["ground_truth_1"], ids["ground_truth_2"]),
        provider_id=provider_id,
    )


def teardown_public_runtime_fixture(
    harness: WorkspaceApiHarness, store: ProviderStore, fixture: PublicRuntimeFixture
) -> None:
    store.delete_provider(fixture.provider_id)
    with harness.session_factory() as session:
        session.execute(delete(GroundTruth).where(GroundTruth.id.in_(fixture.ground_truth_ids)))
        session.execute(delete(TestDocument).where(TestDocument.id.in_(fixture.document_ids)))
        session.execute(delete(TestSet).where(TestSet.id == fixture.dataset_id))
        session.execute(
            delete(WorkflowVersionRecord).where(
                WorkflowVersionRecord.workflow_id.in_(
                    [fixture.minimal_workflow_id, fixture.queue_workflow_id]
                )
            )
        )
        session.execute(
            delete(WorkflowRecord).where(
                WorkflowRecord.id.in_([fixture.minimal_workflow_id, fixture.queue_workflow_id])
            )
        )
        workspace_ids = [fixture.workspace_a_id, fixture.workspace_b_id]
        session.execute(
            delete(WorkspaceMember).where(WorkspaceMember.workspace_id.in_(workspace_ids))
        )
        session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
        session.commit()
