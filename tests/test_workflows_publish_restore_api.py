from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.auth import get_authenticated_context
from app.api.workflows import get_workflow
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.models.workflow import WorkflowDefinition
from app.services.workflow_store import WorkflowStore
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole

TEST_USER_ID = "usr_workflow_publish_restore"
TEST_WORKSPACE_ID = "ws_workflow_publish_restore"


def _sample_definition() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": "utf-8"}},
            {"id": "output_1", "type": "output/markdown", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }


def _fake_auth_context() -> AuthenticatedContext:
    return AuthenticatedContext(
        user=AuthUser(id=TEST_USER_ID, email="tester@example.com", name="Tester"),
        session=AuthSessionInfo(
            id="as_test",
            user_id=TEST_USER_ID,
            expires_at=datetime(2099, 3, 26, tzinfo=timezone.utc),
        ),
        workspace_id=TEST_WORKSPACE_ID,
        role=WorkspaceRole.OWNER,
        capabilities=CAPABILITIES[WorkspaceRole.OWNER],
    )


def _reset_database_runtime() -> None:
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


async def _skip_provider_discovery(_store: object) -> int:
    return 0


@pytest.fixture
def workflow_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'app.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.sqlite3"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AUTH_SESSION_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("SKIP_DAG_INIT", "true")
    monkeypatch.setattr("app.main.discover_seed_configs", _skip_provider_discovery)
    get_settings.cache_clear()
    _reset_database_runtime()

    Base.metadata.create_all(bind=db_session._get_engine())
    with db_session.SessionLocal() as session:
        session.add(
            UserAccount(
                id=TEST_USER_ID,
                email="tester@example.com",
                password_hash="pbkdf2_sha256$390000$00$00",
                name="Tester",
            )
        )
        session.add(
            Workspace(
                id=TEST_WORKSPACE_ID,
                name="Workflow Publish Restore",
                slug=None,
                description=None,
                owner_user_id=TEST_USER_ID,
            )
        )
        session.add(
            WorkspaceMember(
                id="wsm_workflow_publish_restore",
                workspace_id=TEST_WORKSPACE_ID,
                user_id=TEST_USER_ID,
                role=WorkspaceRole.OWNER.value,
            )
        )
        session.commit()

    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()
        _reset_database_runtime()


def _legacy_definition_without_end() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": "utf-8"}},
            {"id": "output_1", "type": "output/plaintext", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
        ],
    }


def _definition_with_multiple_end_nodes() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {"encoding": "utf-8"}},
            {"id": "output_1", "type": "output/plaintext", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
            {"id": "end_2", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "output_1"},
            {"source": "output_1", "target": "end_1"},
            {"source": "output_1", "target": "end_2"},
        ],
    }


def _save_workflow(
    client: TestClient,
    *,
    name: str,
    description: str | None = None,
) -> dict[str, object]:
    payload = {"name": name, "definition": _sample_definition()}
    if description is not None:
        payload["description"] = description
    response = client.post("/api/workflows/save", json=payload)
    assert response.status_code == 200
    return response.json()["data"]


def test_publish_and_restore_workflow_version(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client

        create = client.post(
            "/api/workflows/save",
            json={"name": "wf", "definition": _sample_definition()},
        )
        assert create.status_code == 200
        created = create.json()["data"]
        workflow_id = created["id"]

        publish = client.post(f"/api/workflows/{workflow_id}/publish")
        assert publish.status_code == 200
        assert publish.json()["data"]["version"] == 1

        update = client.post(
            "/api/workflows/save",
            json={
                "workflow_id": workflow_id,
                "workflow_key": created["workflow_key"],
                "base_version": created["latest_version"],
                "definition": {
                    "nodes": [
                        {"id": "input_2", "type": "input/text", "config": {"file": "$file_0"}},
                        {"id": "engine_2", "type": "engine/text", "config": {"encoding": "big5"}},
                        {"id": "output_2", "type": "output/markdown", "config": {}},
                    ],
                    "connections": [
                        {"source": "input_2", "target": "engine_2"},
                        {"source": "engine_2", "target": "output_2"},
                    ],
                },
            },
        )
        assert update.status_code == 200

        restore = client.post(f"/api/workflows/{workflow_id}/versions/1/restore")
        assert restore.status_code == 200
        assert restore.json()["data"]["restored_version"] == 1
        assert restore.json()["data"]["version"] == 3

        detail = client.get(f"/api/workflows/{workflow_id}")
        assert detail.status_code == 200
        assert detail.json()["definition"]["nodes"][1]["id"] == "engine_1"
    finally:
        app.dependency_overrides.clear()


def test_restore_workflow_version_by_workflow_key_route(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client

        create = client.post(
            "/api/workflows/save",
            json={"name": "wf", "definition": _sample_definition()},
        )
        assert create.status_code == 200
        created = create.json()["data"]
        workflow_id = created["id"]
        workflow_key = created["workflow_key"]

        update = client.post(
            "/api/workflows/save",
            json={
                "workflow_id": workflow_id,
                "workflow_key": workflow_key,
                "base_version": created["latest_version"],
                "definition": {
                    "nodes": [
                        {"id": "input_2", "type": "input/text", "config": {"file": "$file_0"}},
                        {"id": "engine_2", "type": "engine/text", "config": {"encoding": "big5"}},
                        {"id": "output_2", "type": "output/markdown", "config": {}},
                    ],
                    "connections": [
                        {"source": "input_2", "target": "engine_2"},
                        {"source": "engine_2", "target": "output_2"},
                    ],
                },
            },
        )
        assert update.status_code == 200

        restore = client.post(f"/api/workflows/{workflow_key}/restore/1")

        assert restore.status_code == 200
        assert restore.json()["data"]["workflow_key"] == workflow_key

        detail = client.get(f"/api/workflows/{workflow_id}")
        assert detail.status_code == 200
        assert detail.json()["definition"]["nodes"][1]["id"] == "engine_1"
    finally:
        app.dependency_overrides.clear()


def test_list_workflows_supports_search_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client
        published = _save_workflow(client, name="Invoice OCR", description="first saved")
        unpublished = _save_workflow(client, name="Receipt Compare", description="invoice fallback")
        _save_workflow(client, name="Archive", description="second saved")

        publish_response = client.post(f"/api/workflows/{published['id']}/publish")
        assert publish_response.status_code == 200

        search_response = client.get(
            "/api/workflows",
            params={"q": "invoice", "sort": "name:asc", "limit": 1, "page": 1},
        )
        assert search_response.status_code == 200
        payload = search_response.json()
        assert payload["meta"]["total"] == 2
        assert len(payload["data"]) == 1
        assert payload["data"][0]["name"] == "Invoice OCR"
        assert payload["data"][0]["published_version"] == 1
        assert payload["data"][0]["latest_version"] == 1

        pagination_response = client.get(
            "/api/workflows",
            params={"q": "invoice", "sort": "name:asc", "limit": 1, "page": 2},
        )
        assert pagination_response.status_code == 200
        page_payload = pagination_response.json()
        assert page_payload["meta"]["page"] == 2
        assert page_payload["meta"]["limit"] == 1
        assert page_payload["meta"]["total"] == 2
        assert page_payload["data"][0]["id"] == unpublished["id"]
        assert page_payload["data"][0]["published_version"] is None
        assert page_payload["data"][0]["latest_version"] == 1
    finally:
        app.dependency_overrides.clear()


def test_list_workflows_returns_empty_result_for_non_matching_query(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client
        _save_workflow(client, name="Invoice OCR", description="first saved")

        response = client.get("/api/workflows", params={"q": "missing"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"] == []
        assert payload["meta"] == {"total": 0, "page": 1, "limit": 20}
    finally:
        app.dependency_overrides.clear()


def test_delete_workflow_handles_success_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client
        workflow_id = str(_save_workflow(client, name="ToDelete")["id"])

        delete_response = client.delete(f"/api/workflows/{workflow_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["success"] is True

        retry_response = client.delete(f"/api/workflows/{workflow_id}")
        assert retry_response.status_code == 404
        assert retry_response.json()["error_code"] == "WORKFLOW_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


def test_update_workflow_metadata(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client
        saved = _save_workflow(client, name="Invoice OCR", description="first saved")
        workflow_id = str(saved["id"])
        publish = client.post(f"/api/workflows/{workflow_id}/publish")
        assert publish.status_code == 200

        response = client.patch(
            f"/api/workflows/{workflow_id}",
            json={"name": "Invoice OCR v2", "description": "updated by review"},
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["name"] == "Invoice OCR v2"
        assert payload["description"] == "updated by review"
        assert payload["published_version"] == 1
        assert payload["latest_version"] == 1

        detail = client.get(f"/api/workflows/{workflow_id}")
        assert detail.status_code == 200
        assert detail.json()["name"] == "Invoice OCR v2"
        assert detail.json()["description"] == "updated by review"
        assert detail.json()["definition"]["nodes"][1]["id"] == "engine_1"
    finally:
        app.dependency_overrides.clear()


def test_update_workflow_metadata_rejects_blank_name(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client
        workflow_id = str(_save_workflow(client, name="Invoice OCR")["id"])

        response = client.patch(
            f"/api/workflows/{workflow_id}",
            json={"name": "   "},
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error_code"] == "WORKFLOW_METADATA_INVALID"
    finally:
        app.dependency_overrides.clear()


def test_save_workflow_ingress_repairs_missing_end_node(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client

        save_response = client.post(
            "/api/workflows/save",
            json={
                "name": "Legacy Missing End",
                "definition": _legacy_definition_without_end(),
            },
        )
        assert save_response.status_code == 200
        workflow_id = save_response.json()["data"]["id"]

        detail_response = client.get(f"/api/workflows/{workflow_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        end_nodes = [node for node in detail["definition"]["nodes"] if node["type"] == "end/final"]
        assert len(end_nodes) == 1
        end_node_id = end_nodes[0]["id"]
        assert {
            "source": "engine_1",
            "target": end_node_id,
            "source_port": None,
            "target_port": None,
        } in detail["definition"]["connections"]
    finally:
        app.dependency_overrides.clear()


def test_import_workflow_ingress_repairs_missing_end_node(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client

        import_response = client.post(
            "/api/workflows/import",
            json={
                "format_version": "1.0",
                "workflow": {
                    "name": "Imported Legacy Missing End",
                    "description": "compatibility test",
                    "definition": _legacy_definition_without_end(),
                },
            },
        )
        assert import_response.status_code == 200
        workflow_id = import_response.json()["data"]["id"]

        detail_response = client.get(f"/api/workflows/{workflow_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        end_nodes = [node for node in detail["definition"]["nodes"] if node["type"] == "end/final"]
        assert len(end_nodes) == 1
        end_node_id = end_nodes[0]["id"]
        assert {
            "source": "engine_1",
            "target": end_node_id,
            "source_port": None,
            "target_port": None,
        } in detail["definition"]["connections"]
    finally:
        app.dependency_overrides.clear()


def test_save_workflow_multiple_end_nodes_returns_blocking_error_without_destructive_repair(
    monkeypatch: pytest.MonkeyPatch,
    workflow_api_client: TestClient,
) -> None:
    store = WorkflowStore()
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)
    app.dependency_overrides[get_authenticated_context] = _fake_auth_context

    try:
        client = workflow_api_client

        save_response = client.post(
            "/api/workflows/save",
            json={
                "name": "Multiple End",
                "definition": _definition_with_multiple_end_nodes(),
            },
        )
        assert save_response.status_code == 422
        payload = save_response.json()
        assert payload["error_code"] == "WORKFLOW_VALIDATION_ERROR"
        assert "errors" in payload["details"]
        codes = {issue["code"] for issue in payload["details"]["errors"]}
        assert "WORKFLOW_MULTIPLE_END" in codes
        assert store.list(workspace_id=TEST_WORKSPACE_ID) == []
    finally:
        app.dependency_overrides.clear()


def test_get_workflow_normalizes_legacy_definition_on_persisted_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkflowStore()
    workflow = store.create(
        name="legacy load",
        description="raw store fixture",
        definition=WorkflowDefinition.model_validate(_legacy_definition_without_end()),
        workspace_id="ws_viewer",
    )
    monkeypatch.setattr("app.api.workflows.get_workflow_store", lambda: store)

    response = asyncio.run(
        get_workflow(
            workflow.id,
            SimpleNamespace(workspace_id="ws_viewer"),
        )
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    node_types = {node["id"]: node["type"] for node in payload["definition"]["nodes"]}
    assert node_types["end_1"] == "end/final"
    assert "output_1" not in node_types

    persisted = store.get(workflow.id, workspace_id="ws_viewer")
    assert persisted is not None
    persisted_node_types = {node.id: node.type for node in persisted.definition.nodes}
    assert persisted_node_types["output_1"] == "output/plaintext"
    assert "end_1" not in persisted_node_types
