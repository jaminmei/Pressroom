from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.ground_truths import get_evaluation_service
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.errors import AppError, ErrorCode
from app.main import app
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.storage.test_set_storage import TestSetStorage
from tests.integration.test_test_set_workspace_rbac import RbacHarness, _register, _switch
from tests.integration.workspace_api_support import (
    add_member,
    create_workspace,
    skip_discover_seed_configs,
)


@pytest.fixture()
def ground_truth_rbac_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[RbacHarness]:
    database_path = tmp_path / "ground-truth-workspace-rbac.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    provider_db_path = tmp_path / "providers.sqlite3"
    provider_key = Fernet.generate_key().decode()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("BACKEND_DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("BACKEND_WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(provider_db_path))
    monkeypatch.setenv("BACKEND_PROVIDER_DB_PATH", str(provider_db_path))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", provider_key)
    monkeypatch.setenv("BACKEND_PROVIDER_ENCRYPTION_KEY", provider_key)
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()
    Base.metadata.create_all(bind=db_session._get_engine())

    from app.repositories.test_set_repository import TestSetRepository

    app.state.test_set_repository = TestSetRepository()
    app.state.ground_truth_repository = GroundTruthRepository()
    app.state.test_set_storage = TestSetStorage(tmp_path / "storage")

    async def _apply_result_as_ground_truth(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            id="gt_apply_1",
            document_id=kwargs["document_id"],
            version=2,
            source="inference_apply",
            format="markdown",
            content="# Applied output",
            source_task_run_id=kwargs["task_run_id"],
            notes=kwargs["notes"],
            created_at=datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc),
        )

    evaluation_service = SimpleNamespace(
        apply_result_as_ground_truth=_apply_result_as_ground_truth,
    )
    app.state.evaluation_service = evaluation_service
    app.dependency_overrides[get_evaluation_service] = lambda: evaluation_service

    with ExitStack() as stack:
        yield RbacHarness(stack=stack)

    app.dependency_overrides.pop(get_evaluation_service, None)


def _create_scoped_document(owner_client: TestClient, workspace_id: str) -> tuple[str, str]:
    created_set = owner_client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": "GT Set", "description": None},
    )
    assert created_set.status_code == 201
    test_set_id = created_set.json()["id"]

    uploaded = owner_client.post(
        f"/api/test-sets/{test_set_id}/documents/upload?workspace_id={workspace_id}",
        files={"files": ("invoice.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["uploaded"][0]["id"]
    return test_set_id, document_id


def test_editor_can_create_and_apply_ground_truth(
    ground_truth_rbac_harness: RbacHarness,
) -> None:
    owner_user = _register(ground_truth_rbac_harness, "owner@example.com")
    editor_user = _register(ground_truth_rbac_harness, "editor@example.com")
    workspace_id = create_workspace(owner_user.client)
    add_member(
        owner_user.client,
        workspace_id=workspace_id,
        user_id=editor_user.user_id,
        role="editor",
    )
    _switch(editor_user.client, workspace_id)

    test_set_id, document_id = _create_scoped_document(owner_user.client, workspace_id)

    created = editor_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth?workspace_id={workspace_id}",
        json={
            "content": "expected content",
            "format": "text",
            "source": "manual_edit",
            "notes": "initial",
        },
    )
    assert created.status_code == 201

    applied = editor_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/apply?workspace_id={workspace_id}",
        json={"task_run_id": "task_eval_1", "notes": "apply"},
    )
    assert applied.status_code == 201


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        (ErrorCode.TASK_NOT_FOUND, 404),
        (ErrorCode.TASK_RESULT_NOT_READY, 409),
    ],
)
def test_apply_ground_truth_maps_task_errors_and_passes_actor_scope(
    ground_truth_rbac_harness: RbacHarness,
    error_code: ErrorCode,
    expected_status: int,
) -> None:
    owner = _register(ground_truth_rbac_harness, f"{error_code.value.lower()}@example.com")
    workspace_id = create_workspace(owner.client)
    test_set_id, document_id = _create_scoped_document(owner.client, workspace_id)
    calls: list[dict[str, object]] = []

    class _RejectingEvaluationService:
        async def apply_result_as_ground_truth(self, **kwargs: object) -> object:
            calls.append(kwargs)
            raise AppError(error_code, "Task output is unavailable.")

    app.dependency_overrides[get_evaluation_service] = _RejectingEvaluationService

    response = owner.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/apply"
        f"?workspace_id={workspace_id}",
        json={"task_run_id": "task_missing", "notes": "apply"},
    )

    assert response.status_code == expected_status
    assert response.json()["error_code"] == error_code.value
    assert calls == [
        {
            "document_id": document_id,
            "task_run_id": "task_missing",
            "notes": "apply",
            "workspace_id": workspace_id,
            "requested_by_user_id": owner.user_id,
        }
    ]


@pytest.mark.parametrize("role", ["viewer", "runner"])
def test_viewer_and_runner_cannot_create_or_apply_ground_truth(
    ground_truth_rbac_harness: RbacHarness,
    role: str,
) -> None:
    owner_user = _register(ground_truth_rbac_harness, "owner@example.com")
    member_user = _register(ground_truth_rbac_harness, f"{role}@example.com")
    workspace_id = create_workspace(owner_user.client)
    add_member(
        owner_user.client,
        workspace_id=workspace_id,
        user_id=member_user.user_id,
        role=role,
    )
    _switch(member_user.client, workspace_id)

    test_set_id, document_id = _create_scoped_document(owner_user.client, workspace_id)

    create_response = member_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth?workspace_id={workspace_id}",
        json={
            "content": "expected content",
            "format": "text",
            "source": "manual_edit",
            "notes": "initial",
        },
    )
    apply_response = member_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/apply?workspace_id={workspace_id}",
        json={"task_run_id": "task_eval_1", "notes": "apply"},
    )

    assert create_response.status_code == 403
    assert apply_response.status_code == 403
    assert create_response.json()["details"]["required_capability"] == "ground_truth.manage"
    assert apply_response.json()["details"]["required_capability"] == "ground_truth.manage"


def test_viewer_can_get_and_list_ground_truth(
    ground_truth_rbac_harness: RbacHarness,
) -> None:
    owner_user = _register(ground_truth_rbac_harness, "owner@example.com")
    viewer_user = _register(ground_truth_rbac_harness, "viewer@example.com")
    workspace_id = create_workspace(owner_user.client)
    add_member(
        owner_user.client,
        workspace_id=workspace_id,
        user_id=viewer_user.user_id,
        role="viewer",
    )
    _switch(viewer_user.client, workspace_id)

    test_set_id, document_id = _create_scoped_document(owner_user.client, workspace_id)
    created = owner_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth?workspace_id={workspace_id}",
        json={
            "content": "expected content",
            "format": "text",
            "source": "manual_edit",
            "notes": "initial",
        },
    )
    assert created.status_code == 201

    latest = viewer_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth?workspace_id={workspace_id}"
    )
    versions = viewer_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions?workspace_id={workspace_id}"
    )
    version_detail = viewer_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions/1"
        f"?workspace_id={workspace_id}"
    )
    missing_version = viewer_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions/99"
        f"?workspace_id={workspace_id}"
    )
    missing_document = viewer_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/doc-missing/ground-truth/versions/1"
        f"?workspace_id={workspace_id}"
    )

    assert latest.status_code == 200
    assert versions.status_code == 200
    assert version_detail.status_code == 200
    assert missing_version.status_code == 404
    assert missing_document.status_code == 404
    assert latest.json()["id"] == created.json()["id"]
    assert versions.json()["total"] == 1
    assert "content" not in versions.json()["items"][0]
    assert version_detail.json()["content"] == "expected content"


def test_cross_workspace_ground_truth_routes_return_404(
    ground_truth_rbac_harness: RbacHarness,
) -> None:
    owner_user = _register(ground_truth_rbac_harness, "owner@example.com")
    first_workspace_id = create_workspace(owner_user.client, name="First")
    second_workspace_id = create_workspace(owner_user.client, name="Second")

    test_set_id, document_id = _create_scoped_document(owner_user.client, first_workspace_id)
    _switch(owner_user.client, second_workspace_id)

    latest = owner_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth"
    )
    versions = owner_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions"
    )
    version_detail = owner_user.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions/1"
    )
    created = owner_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth",
        json={
            "content": "expected content",
            "format": "text",
            "source": "manual_edit",
            "notes": "initial",
        },
    )
    applied = owner_user.client.post(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/apply",
        json={"task_run_id": "task_eval_1", "notes": "apply"},
    )

    assert latest.status_code == 404
    assert versions.status_code == 404
    assert version_detail.status_code == 404
    assert created.status_code == 404
    assert applied.status_code == 404
