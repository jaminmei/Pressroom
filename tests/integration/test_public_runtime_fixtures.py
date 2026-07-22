"""Integration coverage for disposable public runtime fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.models.db.ground_truth import GroundTruth
from app.models.db.test_document import TestDocument as DocumentRecord
from app.models.db.test_set import TestSet as DatasetRecord
from app.models.db.workflow_record import WorkflowRecord
from app.models.db.workspace import Workspace
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from tests.integration.workspace_api_support import WorkspaceApiHarness, create_workspace
from tests.public_runtime_fixture import (
    ROLES,
    RuntimeFixtureContext,
    setup_public_runtime_fixture,
    teardown_public_runtime_fixture,
)


def test_public_runtime_fixture_is_idempotent_isolated_and_disposable(
    workspace_api_harness: WorkspaceApiHarness,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clients = {
        role: workspace_api_harness.register_user(
            f"public_runtime-{role}@example.test", f"Public Runtime {role}"
        )
        for role in ROLES
    }
    foreign = workspace_api_harness.register_user(
        "public_runtime-foreign@example.test", "Public Runtime foreign"
    )
    provider_store = ProviderStore(
        db_path=init_db(tmp_path / "public_runtime-providers.sqlite3"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )
    provider_store.create_provider(
        ModelProviderCreate(
            name="Public Runtime system text fallback",
            provider_type=ProviderType.engine_service,
            engine_category="text",
            base_url="http://text-engine:8000",
            auth_type="none",
            is_default=True,
            scope=ProviderScope.system,
        )
    )
    clients["owner"].client.app.state.provider_store = provider_store
    foreign.client.app.state.provider_store = provider_store
    runtime = RuntimeFixtureContext(
        harness=workspace_api_harness,
        owner=clients["owner"].client,
        users={role: registered.user_id for role, registered in clients.items()},
        provider_store=provider_store,
    )

    first = setup_public_runtime_fixture(runtime, "pytest-runtime")
    second = setup_public_runtime_fixture(runtime, "pytest-runtime")
    manifest_path = tmp_path / "public_runtime-live-fixture.json"
    manifest_path.write_text(first.json() + "\n", encoding="utf-8")
    print(first.json())

    assert first == second
    assert json.loads(capsys.readouterr().out) == json.loads(manifest_path.read_text())
    assert first.workspace_a_id != "ws_legacy" and first.workspace_b_id != "ws_legacy"
    assert set(first.user_ids) == set(ROLES)
    provider = provider_store.get_provider(first.provider_id)
    assert provider is not None and provider.is_default is True
    with workspace_api_harness.session_factory() as session:
        queue_workflow = session.get(WorkflowRecord, first.queue_workflow_id)
        assert queue_workflow is not None
        queue_nodes = queue_workflow.current_definition_json["nodes"]
        assert len(queue_nodes) == 4
        assert queue_nodes[1]["config"] == {
            "provider_id": first.provider_id,
            "max_retries": 3,
            "retry_delay_seconds": 5,
            "cancellation_delay_seconds": 2,
        }
        assert (
            session.scalar(
                select(func.count(DocumentRecord.id)).where(
                    DocumentRecord.test_set_id == first.dataset_id
                )
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(GroundTruth.id)).where(
                    GroundTruth.document_id.in_(first.document_ids)
                )
            )
            == 2
        )

    foreign_workspace_id = create_workspace(foreign.client, name="Foreign")
    assert foreign.client.post(f"/api/workspaces/{foreign_workspace_id}/switch").status_code == 200
    foreign_response = foreign.client.get(f"/api/providers/{first.provider_id}")
    missing_response = foreign.client.get("/api/providers/provider_public_runtime_missing")
    assert foreign_response.status_code == missing_response.status_code == 404
    foreign_error = foreign_response.json()
    missing_error = missing_response.json()
    foreign_error.pop("trace_id")
    missing_error.pop("trace_id")
    assert foreign_error == missing_error
    assert foreign_error["message"] == "Provider not found."

    teardown_public_runtime_fixture(workspace_api_harness, provider_store, first)
    teardown_public_runtime_fixture(workspace_api_harness, provider_store, first)
    with workspace_api_harness.session_factory() as session:
        assert session.get(WorkflowRecord, first.queue_workflow_id) is None
        assert session.get(DatasetRecord, first.dataset_id) is None
        assert session.get(Workspace, first.workspace_a_id) is None
    assert provider_store.get_provider(first.provider_id) is None
