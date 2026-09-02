from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.files import get_file_store
from app.main import app
from tests.integration.workspace_api_support import (
    WorkspaceApiHarness,
    add_member,
    create_workspace,
)


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "StrongerPassword123!",
            "name": email,
        },
    )
    assert response.status_code == 201
    return str(response.json()["data"]["user"]["id"])


def _definition() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine", "type": "engine/text", "config": {}},
            {"id": "end", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input", "target": "engine"},
            {"source": "engine", "target": "end"},
        ],
    }


def test_workflow_execute_uses_workspace_shared_file_store(
    workspace_api_harness: WorkspaceApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = workspace_api_harness
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with TestClient(app) as owner_client:
        owner_id = _register(owner_client, "file-owner@example.com")
        runner_client = TestClient(app)
        try:
            runner_id = _register(runner_client, "file-runner@example.com")
            workspace_a = create_workspace(owner_client, name="Workspace A")
            workspace_b = create_workspace(owner_client, name="Workspace B")
            add_member(
                owner_client,
                workspace_id=workspace_a,
                user_id=runner_id,
                role="runner",
            )
            assert runner_client.post(f"/api/workspaces/{workspace_a}/switch").status_code == 200

            workflow_a = owner_client.post(
                f"/api/workflows?workspace_id={workspace_a}",
                json={"name": "Owned file workflow", "definition": _definition()},
            )
            workflow_b = owner_client.post(
                f"/api/workflows?workspace_id={workspace_b}",
                json={"name": "Other workspace workflow", "definition": _definition()},
            )
            assert workflow_a.status_code == 201
            assert workflow_b.status_code == 201

            uploaded = owner_client.post(
                f"/api/files/upload?workspace_id={workspace_a}",
                files={"file": ("owned.txt", b"owned content", "text/plain")},
            )
            assert uploaded.status_code == 200
            file_id = str(uploaded.json()["file_id"])

            orchestrator = app.state.task_orchestrator
            assert orchestrator._file_store is get_file_store()
            record = get_file_store().get(file_id)
            assert record is not None
            assert record.workspace_id == workspace_a
            assert record.uploaded_by_user_id == owner_id
            cross_workspace = owner_client.post(
                f"/api/workflows/{workflow_b.json()['workflow_id']}/execute"
                f"?workspace_id={workspace_b}",
                json={"file_ids": [file_id]},
            )
            assert cross_workspace.status_code == 400

            shared_member = runner_client.post(
                f"/api/workflows/{workflow_a.json()['workflow_id']}/execute"
                f"?workspace_id={workspace_a}",
                json={"file_ids": [file_id]},
            )
            assert shared_member.status_code == 202
            assert shared_member.json()["task_id"] in orchestrator._tasks
        finally:
            runner_client.close()
