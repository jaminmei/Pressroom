"""Workspace deletion and integrity checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.services.workspace_service import assert_workspace_active
from tests.integration.workspace_api_support import WorkspaceApiHarness, create_workspace


def _seed_business_data(harness: WorkspaceApiHarness, workspace_id: str) -> None:
    with harness.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO workflows (id, workflow_key, name, workspace_id, "
                "current_definition_json, latest_version) VALUES "
                "('wf_delete', 'wk_delete', 'Delete me', :workspace_id, '{}', 1)"
            ),
            {"workspace_id": workspace_id},
        )
        session.execute(
            text(
                "INSERT INTO test_sets (id, name, workspace_id, document_count) "
                "VALUES ('db_delete', 'Database', :workspace_id, 0)"
            ),
            {"workspace_id": workspace_id},
        )
        session.execute(
            text(
                "INSERT INTO evaluation_runs "
                "(id, test_set_id, workspace_id, workflow_id, status, total_documents, "
                "completed_count, failed_count) VALUES "
                "('er_delete', 'db_delete', :workspace_id, 'wf_delete', 'pending', 0, 0, 0)"
            ),
            {"workspace_id": workspace_id},
        )
        session.execute(
            text(
                "INSERT INTO task_runs (id, workspace_id, workflow_id) "
                "VALUES ('tr_delete', :workspace_id, 'wf_delete')"
            ),
            {"workspace_id": workspace_id},
        )
        session.commit()


def _seed_provider(database_path: Path, workspace_id: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE model_providers "
            "(id TEXT PRIMARY KEY, scope TEXT NOT NULL, workspace_id TEXT, is_default INTEGER)"
        )
        connection.execute(
            "INSERT INTO model_providers VALUES ('provider_delete', 'workspace', ?, 0)",
            (workspace_id,),
        )


def test_deletion_impact_returns_all_business_counts(
    workspace_api_harness: WorkspaceApiHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner = workspace_api_harness.register_user("impact@example.com", "Impact")
    workspace_id = create_workspace(owner.client)
    provider_path = tmp_path / "providers.sqlite3"
    monkeypatch.setenv("PROVIDER_DB_PATH", str(provider_path))
    _seed_business_data(workspace_api_harness, workspace_id)
    _seed_provider(provider_path, workspace_id)

    response = owner.client.get(f"/api/workspaces/{workspace_id}/deletion-impact")

    assert response.status_code == 200
    assert response.json() == {
        "can_delete": False,
        "counts": {
            "members_excluding_owner": 0,
            "workflows": 1,
            "databases": 1,
            "evaluation_runs": 1,
            "task_runs": 1,
            "workspace_providers": 1,
        },
    }


def test_delete_rechecks_and_recovers_active_when_nonempty(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("nonempty@example.com", "Nonempty")
    workspace_id = create_workspace(owner.client)
    _seed_business_data(workspace_api_harness, workspace_id)

    response = owner.client.delete(f"/api/workspaces/{workspace_id}")

    assert response.status_code == 409
    assert response.json()["error_code"] == "WORKSPACE_NOT_EMPTY"
    assert response.json()["details"]["counts"]["workflows"] == 1
    with workspace_api_harness.session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        assert workspace.status == "active"


def test_empty_delete_repairs_last_workspace(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("empty@example.com", "Empty")
    create_workspace(owner.client, name="Fallback")
    deleted_id = create_workspace(owner.client, name="Deleted")
    switch = owner.client.post(f"/api/workspaces/{deleted_id}/switch")
    assert switch.status_code == 200

    response = owner.client.delete(f"/api/workspaces/{deleted_id}")

    assert response.status_code == 204
    with workspace_api_harness.session_factory() as session:
        user = session.get(UserAccount, owner.user_id)
        assert user is not None
        assert user.last_workspace_id != deleted_id
        assert user.last_workspace_id is not None
        assert session.get(Workspace, deleted_id) is None


def test_delete_failure_rolls_back_without_leaving_deleting_status(
    workspace_api_harness: WorkspaceApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = workspace_api_harness.register_user("rollback@example.com", "Rollback")
    fallback_id = create_workspace(owner.client, name="Fallback")
    deleted_id = create_workspace(owner.client, name="Delete target")
    assert owner.client.post(f"/api/workspaces/{deleted_id}/switch").status_code == 200
    original_delete = Session.delete

    def _fail_workspace_delete(session: Session, instance: object) -> None:
        if isinstance(instance, Workspace) and instance.id == deleted_id:
            raise RuntimeError("simulated delete failure")
        original_delete(session, instance)

    monkeypatch.setattr(Session, "delete", _fail_workspace_delete)

    with pytest.raises(RuntimeError, match="simulated delete failure"):
        owner.client.delete(f"/api/workspaces/{deleted_id}")

    with workspace_api_harness.session_factory() as session:
        workspace = session.get(Workspace, deleted_id)
        user = session.get(UserAccount, owner.user_id)
        assert workspace is not None
        assert workspace.status == "active"
        assert user is not None
        assert user.last_workspace_id == deleted_id
        assert session.get(Workspace, fallback_id) is not None


def test_deleting_workspace_blocks_new_scoped_creates(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("deleting@example.com", "Deleting")
    workspace_id = create_workspace(owner.client)
    with workspace_api_harness.session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        workspace.status = "deleting"
        session.commit()

    with pytest.raises(AppError):
        with assert_workspace_active(workspace_id):
            raise AssertionError("deleting workspace must not yield the create lock")
