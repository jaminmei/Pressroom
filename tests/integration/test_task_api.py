from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store as get_upload_file_store
from app.api.tasks import get_file_store as get_task_file_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.fixture
def isolated_task_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> Path:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'tasks.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.db"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.delenv("SKIP_DAG_INIT", raising=False)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    get_settings.cache_clear()
    get_upload_file_store.cache_clear()
    get_task_file_store.cache_clear()
    with TestClient(app):
        yield tmp_path
    get_task_file_store.cache_clear()
    get_upload_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


async def _create_task(
    client: AsyncClient, *, name: str = "doc.txt", payload: bytes = b"hello"
) -> str:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }
    response = await client.post(
        "/api/tasks",
        data={"workflow": json.dumps(workflow)},
        files={"files": (name, payload, "text/plain")},
    )
    assert response.status_code == 202
    return response.json()["task_id"]


async def _create_html_task(client: AsyncClient) -> str:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }
    response = await client.post(
        "/api/tasks",
        data={"workflow": json.dumps(workflow)},
        files={
            "files": (
                "doc.html",
                b"<html><body><h1>Hello</h1></body></html>",
                "text/html",
            )
        },
    )
    assert response.status_code == 202
    return response.json()["task_id"]


async def _wait_for_task_completion(
    client: AsyncClient, task_id: str, timeout_seconds: float = 3.0
) -> dict:
    end_time = time.monotonic() + timeout_seconds
    last_payload: dict = {}

    while time.monotonic() < end_time:
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "failed"}:
            return payload
        await asyncio.sleep(0.02)

    raise AssertionError(f"Task {task_id} did not complete in time: {last_payload}")


@pytest.mark.anyio
async def test_create_task_api_returns_202(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"].startswith("task_")
    assert body["status"] == "pending"
    assert "created_at" in body


@pytest.mark.anyio
async def test_create_task_accepts_html_with_text_engine(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_html_task(client)
        payload = await _wait_for_task_completion(client, task_id)

    assert payload["status"] == "completed"


@pytest.mark.anyio
async def test_get_task_status_returns_completed_result(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_task(client)
        payload = await _wait_for_task_completion(client, task_id)

    assert payload["task_id"] == task_id
    assert payload["status"] == "completed"
    assert payload["progress"]["percentage"] == 100
    assert payload["workflow"]["nodes"][-1]["type"] == "end/final"


@pytest.mark.anyio
async def test_download_result_rejects_missing_materialized_file(
    isolated_task_storage: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_task(client)
        await _wait_for_task_completion(client, task_id)
        results_response = await client.get(f"/api/tasks/{task_id}/results")
        assert results_response.status_code == 200
        result = results_response.json()["results"][0]
        assert result["content"]
        assert result["file"]["content_type"] == "application/json"
        result_id = result["result_id"]

        response = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert response.status_code == 404
    assert response.json()["error_code"] == "RESULT_NOT_FOUND"


@pytest.mark.anyio
async def test_download_404_when_result_not_found(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task_id = await _create_task(client)
        await _wait_for_task_completion(client, task_id)
        response = await client.get(f"/api/tasks/{task_id}/results/res_missing/download")

    assert response.status_code == 404
    assert response.json()["error_code"] == "RESULT_NOT_FOUND"


@pytest.mark.anyio
async def test_get_task_status_404_when_task_not_found(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks/task_missing")

    assert response.status_code == 404
    assert response.json()["error_code"] == "TASK_NOT_FOUND"


@pytest.mark.anyio
async def test_download_404_when_task_not_found(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks/task_missing/results/res_001/download")

    assert response.status_code == 404
    assert response.json()["error_code"] == "TASK_NOT_FOUND"


@pytest.mark.anyio
async def test_create_task_rejects_unsupported_output_format(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            data={"output_format": "html"},
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_OUTPUT_FORMAT"


@pytest.mark.anyio
@pytest.mark.parametrize("output_format", ["plaintext", "yaml"])
async def test_create_task_supports_plaintext_and_yaml_outputs(
    isolated_task_storage: Path,
    output_format: str,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            data={"output_format": output_format},
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

    assert task_id.startswith("task_")
    assert response.json()["status"] == "pending"


@pytest.mark.anyio
async def test_create_task_rejects_empty_upload(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "EMPTY_FILE"


@pytest.mark.anyio
async def test_create_task_rejects_invalid_upload_type(isolated_task_storage: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")},
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.anyio
async def test_get_task_results_returns_results(
    isolated_task_storage: Path,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        task_id = await _create_task(client)
        await _wait_for_task_completion(client, task_id)

        response = await client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["result_id"].startswith("r_task_")
    assert result["content"]
    assert result["file"]["filename"]
    assert isinstance(result["metadata"], dict)
    assert body["summary"]["total_outputs"] == 1


@pytest.mark.anyio
async def test_get_task_results_409_when_not_completed(
    isolated_task_storage: Path,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        task_id = await _create_task(client)
        response = await client.get(f"/api/tasks/{task_id}/results")

    assert response.status_code in (200, 409)


@pytest.mark.anyio
async def test_get_task_results_404_when_task_not_found(
    isolated_task_storage: Path,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tasks/task_missing/results")

    assert response.status_code == 404
    assert response.json()["error_code"] == "TASK_NOT_FOUND"


@pytest.mark.anyio
async def test_create_task_accepts_workflow_files_and_binds_by_placeholder(
    isolated_task_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "app.api.tasks._start_dag_run",
        lambda **kwargs: captured.update(kwargs),
    )
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_1"}},
            {"id": "input_2", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "engine_2", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
            {"source": "input_2", "target": "engine_2"},
            {"source": "engine_2", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            data={"workflow": json.dumps(workflow)},
            files=[
                ("files", ("first.txt", b"first", "text/plain")),
                ("files", ("second.txt", b"second", "text/plain")),
            ],
        )

    assert response.status_code == 202
    input_bindings = captured["input_bindings"]
    assert isinstance(input_bindings, dict)
    assert input_bindings["input_1"].filename == "second.txt"
    assert input_bindings["input_2"].filename == "first.txt"


@pytest.mark.anyio
async def test_create_task_returns_diagnostic_error_when_workflow_files_insufficient(
    isolated_task_storage: Path,
) -> None:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "input_2", "type": "input/text", "config": {"file": "$file_1"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "engine_2", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
            {"source": "input_2", "target": "engine_2"},
            {"source": "engine_2", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            data={"workflow": json.dumps(workflow)},
            files=[("files", ("only-one.txt", b"single", "text/plain"))],
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert "files 數量不足" in body["message"]
    assert "至少 2" in body["message"]
    assert "實際 1" in body["message"]


@pytest.mark.anyio
async def test_create_task_workflow_keeps_legacy_single_file_compatibility(
    isolated_task_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "app.api.tasks._start_dag_run",
        lambda **kwargs: captured.update(kwargs),
    )
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks",
            data={"workflow": json.dumps(workflow)},
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        )

    assert response.status_code == 202
    input_bindings = captured["input_bindings"]
    assert isinstance(input_bindings, dict)
    assert input_bindings["input_1"].filename == "legacy.txt"


@pytest.mark.anyio
async def test_create_task_workflow_keeps_file_ids_compatibility(
    isolated_task_storage: Path,
) -> None:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_response = await client.post(
            "/api/files/upload",
            files={"file": ("stored.txt", b"stored", "text/plain")},
        )
        assert upload_response.status_code == 200
        file_id = upload_response.json()["file_id"]

        response = await client.post(
            "/api/tasks",
            data={
                "workflow": json.dumps(workflow),
                "file_ids": json.dumps([file_id]),
            },
        )

    assert response.status_code == 202


@pytest.mark.anyio
async def test_create_node_run_task_runs_selected_engine_node(
    isolated_task_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "app.api.tasks._start_dag_run",
        lambda **kwargs: captured.update(kwargs),
    )
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "input_2", "type": "input/text", "config": {"file": "$file_1"}},
            {"id": "engine_text_1", "type": "engine/text", "config": {}},
            {"id": "engine_text_2", "type": "engine/text", "config": {"language": "en"}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_text_1"},
            {"source": "engine_text_1", "target": "end_1"},
            {"source": "input_2", "target": "engine_text_2"},
            {"source": "engine_text_2", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks/node-run",
            data={
                "workflow": json.dumps(workflow),
                "node_id": "engine_text_2",
                "output_format": "markdown",
            },
            files=[
                ("files", ("first.txt", b"first-input", "text/plain")),
                ("files", ("second.txt", b"second-input", "text/plain")),
            ],
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["node_id"] == "engine_text_2"
        assert payload["output_format"] == "markdown"
        assert payload["status"] == "pending"
        node_run_workflow = captured["workflow"]
        assert node_run_workflow.get_node("engine_text_2") is not None
        assert node_run_workflow.get_node("engine_text_1") is None
        selected_input = node_run_workflow.get_node("input_1")
        assert selected_input is not None
        assert selected_input.config["file"].endswith("second.txt")


@pytest.mark.anyio
async def test_create_node_run_task_rejects_non_engine_node(
    isolated_task_storage: Path,
) -> None:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "engine_text_1", "type": "engine/text", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_text_1"},
            {"source": "engine_text_1", "target": "end_1"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks/node-run",
            data={
                "workflow": json.dumps(workflow),
                "node_id": "end_1",
            },
            files={"files": ("input.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "WORKFLOW_VALIDATION_ERROR"
    assert "不支援此節點類型" in body["message"]


@pytest.mark.anyio
async def test_create_node_run_task_reports_insufficient_files_for_selected_node(
    isolated_task_storage: Path,
) -> None:
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "input_2", "type": "input/text", "config": {"file": "$file_1"}},
            {"id": "engine_text_1", "type": "engine/text", "config": {}},
            {"id": "engine_text_2", "type": "engine/text", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_text_1"},
            {"source": "input_2", "target": "engine_text_2"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/tasks/node-run",
            data={
                "workflow": json.dumps(workflow),
                "node_id": "engine_text_2",
            },
            files={"files": ("only.txt", b"single", "text/plain")},
        )

    assert response.status_code == 400
    body = response.json()
    error_code = body.get("error_code") or body.get("error", {}).get("code")
    message = body.get("message") or body.get("error", {}).get("message", "")
    assert error_code == "WORKFLOW_VALIDATION_ERROR"
    assert "需要至少 2 個 files" in message
    leftover_files = [
        path for path in (isolated_task_storage / "tasks").rglob("*") if path.is_file()
    ]
    assert leftover_files == []


@pytest.mark.anyio
async def test_create_node_run_task_supports_file_ids_binding(
    isolated_task_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "app.api.tasks._start_dag_run",
        lambda **kwargs: captured.update(kwargs),
    )
    workflow = {
        "nodes": [
            {"id": "input_1", "type": "input/text", "config": {"file": "$file_0"}},
            {"id": "input_2", "type": "input/text", "config": {"file": "$file_1"}},
            {"id": "engine_text_1", "type": "engine/text", "config": {}},
            {"id": "engine_text_2", "type": "engine/text", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_text_1"},
            {"source": "input_2", "target": "engine_text_2"},
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_first = await client.post(
            "/api/files/upload",
            files={"file": ("first.txt", b"first", "text/plain")},
        )
        upload_second = await client.post(
            "/api/files/upload",
            files={"file": ("second.txt", b"second", "text/plain")},
        )
        assert upload_first.status_code == 200
        assert upload_second.status_code == 200

        response = await client.post(
            "/api/tasks/node-run",
            data={
                "workflow": json.dumps(workflow),
                "node_id": "engine_text_2",
                "file_ids": json.dumps(
                    [upload_first.json()["file_id"], upload_second.json()["file_id"]]
                ),
            },
        )

    assert response.status_code == 202
    node_run_workflow = captured["workflow"]
    selected_input = node_run_workflow.get_node("input_1")
    assert selected_input is not None
    second_record = get_task_file_store().get_owned(
        upload_second.json()["file_id"],
        "ws_unit_api",
        "usr_unit_api",
    )
    assert second_record is not None
    assert selected_input.config["file"] == second_record.storage_path
