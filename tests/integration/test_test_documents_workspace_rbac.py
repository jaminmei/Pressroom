from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import WorkspaceRole
from tests.integration.workspace_api_support import (
    RegisteredClient,
    add_member,
    create_workspace,
    reset_db_runtime,
    skip_discover_seed_configs,
)


@dataclass(frozen=True, slots=True)
class RbacHarness:
    stack: ExitStack


@pytest.fixture()
def test_documents_rbac_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[RbacHarness]:
    database_path = tmp_path / "test-documents-workspace-rbac.sqlite3"
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
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())

    with ExitStack() as stack:
        yield RbacHarness(stack=stack)
    reset_db_runtime()


def _register(harness: RbacHarness, email: str) -> RegisteredClient:
    client = harness.stack.enter_context(TestClient(app))
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongerPassword123!", "name": email},
    )
    assert response.status_code == 201
    return RegisteredClient(client=client, user_id=response.json()["data"]["user"]["id"])


def _switch(client: TestClient, workspace_id: str) -> None:
    response = client.post(f"/api/workspaces/{workspace_id}/switch")
    assert response.status_code == 200


def _add_member_directly(workspace_id: str, user_id: str, role: WorkspaceRole) -> None:
    with db_session.SessionLocal() as session:
        session.add(
            WorkspaceMember(
                id=f"wsm_{uuid4()}",
                workspace_id=workspace_id,
                user_id=user_id,
                role=role.value,
            )
        )
        session.commit()


def _create_test_set(client: TestClient, workspace_id: str, name: str = "Docs") -> str:
    response = client.post(
        f"/api/test-sets?workspace_id={workspace_id}",
        json={"name": name, "description": None},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload_pdf(
    client: TestClient,
    test_set_id: str,
    filename: str = "invoice.pdf",
    workspace_id: str | None = None,
) -> str:
    url = f"/api/test-sets/{test_set_id}/documents/upload"
    if workspace_id is not None:
        url = f"{url}?workspace_id={workspace_id}"
    response = client.post(
        url,
        files=[("files", (filename, b"%PDF-1.4 fake", "application/pdf"))],
    )
    assert response.status_code == 201
    assert response.json()["errors"] == []
    return response.json()["uploaded"][0]["id"]


def test_editor_can_access_documents_via_parent_test_set_workspace(
    test_documents_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_documents_rbac_harness, "owner@example.com")
    editor = _register(test_documents_rbac_harness, "editor@example.com")
    workspace_id = create_workspace(owner.client)
    add_member(
        owner.client,
        workspace_id=workspace_id,
        user_id=editor.user_id,
        role=WorkspaceRole.EDITOR.value,
    )
    _switch(editor.client, workspace_id)

    test_set_id = _create_test_set(owner.client, workspace_id)
    document_id = _upload_pdf(editor.client, test_set_id, workspace_id=workspace_id)

    listed = editor.client.get(f"/api/test-sets/{test_set_id}/documents")
    detail = editor.client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    file_response = editor.client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}/file")
    deleted = editor.client.delete(f"/api/test-sets/{test_set_id}/documents/{document_id}")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == document_id
    assert detail.status_code == 200
    assert detail.json()["id"] == document_id
    assert file_response.status_code == 200
    assert file_response.content == b"%PDF-1.4 fake"
    assert deleted.status_code == 204


def test_runner_upload_forbidden_and_cross_workspace_access_hidden(
    test_documents_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_documents_rbac_harness, "owner@example.com")
    runner = _register(test_documents_rbac_harness, "runner@example.com")
    outsider = _register(test_documents_rbac_harness, "outsider@example.com")

    workspace_id = create_workspace(owner.client, name="Primary")
    _add_member_directly(workspace_id, runner.user_id, WorkspaceRole.RUNNER)
    _switch(runner.client, workspace_id)

    test_set_id = _create_test_set(owner.client, workspace_id, name="Scoped Docs")
    document_id = _upload_pdf(
        owner.client,
        test_set_id,
        filename="owner.pdf",
        workspace_id=workspace_id,
    )

    runner_upload = runner.client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("runner.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )

    outsider_workspace_id = create_workspace(outsider.client, name="Other")
    _switch(outsider.client, outsider_workspace_id)

    list_response = outsider.client.get(f"/api/test-sets/{test_set_id}/documents")
    detail_response = outsider.client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    file_response = outsider.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/file"
    )
    thumbnail_response = outsider.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail"
    )
    delete_response = outsider.client.delete(
        f"/api/test-sets/{test_set_id}/documents/{document_id}"
    )

    assert runner_upload.status_code == 403
    assert runner_upload.json()["details"]["required_capability"] == "document.upload"
    assert list_response.status_code == 404
    assert detail_response.status_code == 404
    assert file_response.status_code == 404
    assert thumbnail_response.status_code == 404
    assert delete_response.status_code == 404


def test_document_direct_url_hidden_when_active_workspace_mismatches(
    test_documents_rbac_harness: RbacHarness,
) -> None:
    owner = _register(test_documents_rbac_harness, "owner@example.com")
    workspace_a = create_workspace(owner.client, name="Workspace A")
    workspace_b = create_workspace(owner.client, name="Workspace B")

    test_set_id = _create_test_set(owner.client, workspace_a, name="Scoped Docs")
    document_id = _upload_pdf(
        owner.client,
        test_set_id,
        filename="owner.pdf",
        workspace_id=workspace_a,
    )
    _switch(owner.client, workspace_b)

    list_response = owner.client.get(f"/api/test-sets/{test_set_id}/documents")
    detail_response = owner.client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    file_response = owner.client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}/file")
    thumbnail_response = owner.client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail"
    )

    assert list_response.status_code == 404
    assert detail_response.status_code == 404
    assert file_response.status_code == 404
    assert thumbnail_response.status_code == 404
