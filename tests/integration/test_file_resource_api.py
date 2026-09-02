from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.api.files import get_file_store
from app.config import get_settings
from app.models.db.file_resource import FileResource
from app.models.db.task_run import TaskRun
from app.models.db.task_run_file import TaskRunFile
from app.repositories.task_run_repository import TaskRunRepository
from app.storage.local import get_storage
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)


@pytest.fixture
def file_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_ROOT", str(root))
    get_settings.cache_clear()
    get_storage.cache_clear()
    yield root
    get_storage.cache_clear()
    get_settings.cache_clear()


def test_file_resource_is_durable_shared_and_workspace_scoped(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("file-owner@example.com", "File Owner")
    runner = workspace_api_harness.register_user("file-runner@example.com", "File Runner")
    workspace_a = create_workspace(owner.client, name="File Workspace A")
    workspace_b = create_workspace(owner.client, name="File Workspace B")
    add_member(
        owner.client,
        workspace_id=workspace_a,
        user_id=runner.user_id,
        role="runner",
    )

    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_a},
        files={"file": ("sample.txt", b"shared content", "text/plain")},
    )
    assert uploaded.status_code == 201
    metadata = uploaded.json()
    file_id = str(metadata["file_id"])
    assert metadata["sha256"]
    assert metadata["status"] == "active"
    assert "storage_key" not in metadata

    listed = runner.client.get("/api/files", params={"workspace_id": workspace_a})
    assert listed.status_code == 200
    assert [item["file_id"] for item in listed.json()["items"]] == [file_id]

    downloaded = runner.client.get(
        f"/api/files/{file_id}/content",
        params={"workspace_id": workspace_a},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"shared content"
    assert downloaded.headers["etag"].startswith('"sha256:')

    cross_workspace = owner.client.get(
        f"/api/files/{file_id}",
        params={"workspace_id": workspace_b},
    )
    assert cross_workspace.status_code == 404

    # A new facade instance reads the same database fact source.
    from app.services.file_store import FileStore

    assert FileStore().get_scoped(file_id, workspace_a) is not None


def test_file_delete_reports_run_references_before_soft_delete(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("delete-owner@example.com", "Delete Owner")
    workspace_id = create_workspace(owner.client, name="Delete Workspace")
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("referenced.txt", b"referenced", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])

    with workspace_api_harness.session_factory() as session:
        session.add(
            TaskRun(
                id="run-file-reference",
                status="running",
                workspace_id=workspace_id,
                input_files_json=json.dumps([{"file_id": file_id}]),
            )
        )
        session.commit()

    impact = owner.client.get(
        f"/api/files/{file_id}/deletion-impact",
        params={"workspace_id": workspace_id},
    )
    assert impact.status_code == 200
    assert impact.json() == {
        "can_delete": False,
        "file_id": file_id,
        "run_references": 1,
        "active_run_references": 1,
        "reason": "referenced_by_runs",
    }

    blocked = owner.client.delete(
        f"/api/files/{file_id}",
        params={"workspace_id": workspace_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "FILE_IN_USE"

    with workspace_api_harness.session_factory() as session:
        session.delete(session.get(TaskRun, "run-file-reference"))
        session.commit()

    deleted = owner.client.delete(
        f"/api/files/{file_id}",
        params={"workspace_id": workspace_id},
    )
    assert deleted.status_code == 204
    assert get_file_store().get_scoped(file_id, workspace_id) is None
    retained = get_file_store().get_scoped(file_id, workspace_id, include_deleted=True)
    assert retained is not None
    assert retained.status == "deleted"


def test_file_capabilities_keep_upload_and_delete_out_of_viewer_role(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("cap-owner@example.com", "Capability Owner")
    viewer = workspace_api_harness.register_user("cap-viewer@example.com", "Capability Viewer")
    workspace_id = create_workspace(owner.client, name="Capability Workspace")
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=viewer.user_id,
        role="viewer",
    )
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("visible.txt", b"visible", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])

    assert (
        viewer.client.get(
            f"/api/files/{file_id}", params={"workspace_id": workspace_id}
        ).status_code
        == 200
    )
    denied_upload = viewer.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("denied.txt", b"denied", "text/plain")},
    )
    denied_delete = viewer.client.delete(
        f"/api/files/{file_id}", params={"workspace_id": workspace_id}
    )
    assert denied_upload.status_code == 403
    assert denied_delete.status_code == 403


def test_file_quota_does_not_retain_rejected_storage_content(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = workspace_api_harness.register_user("quota-owner@example.com", "Quota Owner")
    workspace_id = create_workspace(owner.client, name="Quota Workspace")
    monkeypatch.setenv("WORKSPACE_FILE_QUOTA_BYTES", "5")
    get_settings.cache_clear()

    response = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("too-large.txt", b"123456", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_QUOTA_EXCEEDED"
    assert response.json()["details"] == {
        "quota_bytes": 5,
        "used_bytes": 0,
        "requested_bytes": 6,
    }
    assert not any(path.is_file() for path in file_storage.rglob("*"))


def test_file_cleanup_failure_is_compensated_in_metadata(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("cleanup-owner@example.com", "Cleanup Owner")
    workspace_id = create_workspace(owner.client, name="Cleanup Workspace")
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("cleanup.txt", b"cleanup", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])
    monkeypatch.setattr(
        get_storage(),
        "delete_file",
        AsyncMock(side_effect=OSError("simulated cleanup failure")),
    )

    response = owner.client.delete(
        f"/api/files/{file_id}",
        params={"workspace_id": workspace_id},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "FILE_CLEANUP_FAILED"
    retained = get_file_store().get_scoped(file_id, workspace_id, include_deleted=True)
    assert retained is not None
    assert retained.status == "cleanup_failed"

    monkeypatch.setattr(get_storage(), "delete_file", AsyncMock(return_value=None))
    retried = owner.client.delete(
        f"/api/files/{file_id}",
        params={"workspace_id": workspace_id},
    )
    assert retried.status_code == 204
    completed = get_file_store().get_scoped(file_id, workspace_id, include_deleted=True)
    assert completed is not None
    assert completed.status == "deleted"


def test_deleted_file_metadata_obeys_retention_policy(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("retention-owner@example.com", "Retention Owner")
    workspace_id = create_workspace(owner.client, name="Retention Workspace")
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("retained.txt", b"retained", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])
    assert (
        owner.client.delete(
            f"/api/files/{file_id}",
            params={"workspace_id": workspace_id},
        ).status_code
        == 204
    )
    with workspace_api_harness.session_factory() as session:
        row = session.get(FileResource, file_id)
        assert row is not None
        row.deleted_at = (datetime.now(timezone.utc) - timedelta(days=8)).replace(tzinfo=None)
        session.add(row)
        session.commit()

    purged = get_file_store().purge_expired_deleted_metadata(retention_days=7)

    assert purged == 1
    assert get_file_store().get_scoped(file_id, workspace_id, include_deleted=True) is None


def test_workspace_deletion_requires_file_cleanup_first(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("workspace-file@example.com", "File Owner")
    workspace_id = create_workspace(owner.client, name="Workspace File Cleanup")
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("workspace.txt", b"workspace", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])

    impact = owner.client.get(f"/api/workspaces/{workspace_id}/deletion-impact")
    blocked = owner.client.delete(f"/api/workspaces/{workspace_id}")

    assert impact.status_code == 200
    assert impact.json()["counts"]["files"] == 1
    assert blocked.status_code == 409
    assert (
        owner.client.delete(
            f"/api/files/{file_id}", params={"workspace_id": workspace_id}
        ).status_code
        == 204
    )
    assert owner.client.delete(f"/api/workspaces/{workspace_id}").status_code == 204


def test_task_run_file_association_is_normalized_and_legacy_match_is_exact(
    workspace_api_harness: WorkspaceApiHarness,
    file_storage: Path,
) -> None:
    del file_storage
    owner = workspace_api_harness.register_user("association-owner@example.com", "Owner")
    workspace_id = create_workspace(owner.client, name="Association Workspace")
    uploaded = owner.client.post(
        "/api/files",
        params={"workspace_id": workspace_id},
        files={"file": ("association.txt", b"association", "text/plain")},
    )
    file_id = str(uploaded.json()["file_id"])
    now = datetime.now(timezone.utc)
    asyncio.run(
        TaskRunRepository().upsert_snapshot(
            task_id="run-normalized-file",
            status="running",
            workflow_id="workflow-file",
            workflow_name="File workflow",
            workspace_id=workspace_id,
            created_at=now,
            completed_at=None,
            duration_ms=None,
            node_summary={"total": 1, "completed": 0, "failed": 0},
            result_preview=None,
            results=None,
            error=None,
            input_files=[{"node_id": "input", "file_id": file_id}],
            workflow={"nodes": [], "connections": []},
            updated_at=now,
        )
    )
    with workspace_api_harness.session_factory() as session:
        association = session.get(TaskRunFile, ("run-normalized-file", file_id))
        assert association is not None
        session.add(
            TaskRun(
                id="run-similar-file-id",
                status="running",
                workspace_id=workspace_id,
                input_files_json=json.dumps([{"file_id": f"{file_id}-other"}]),
            )
        )
        session.commit()

    impact = get_file_store().deletion_impact(file_id, workspace_id)

    assert impact is not None
    assert impact.run_references == 1
    assert impact.active_run_references == 1
