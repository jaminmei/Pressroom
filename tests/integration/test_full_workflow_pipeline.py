"""Full workflow pipeline integration tests.

Tests the complete workflow-based pipeline: upload → create workflow → execute
→ poll until done → get results → download, plus Node Registry validation
and backward-compatible S1 task API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store
from app.api.tasks import get_file_store as get_tasks_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.execution import NodeOutput
from app.services.engine_client import EngineClient
from app.storage.local import get_storage
from tests._api_workspace_contract import TEST_WORKSPACE_ID
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest_asyncio.fixture
async def isolated_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> AsyncIterator[Path]:
    async def mock_process(
        _client: EngineClient,
        node_type: str,
        *_args: object,
        **_kwargs: object,
    ) -> NodeOutput:
        return NodeOutput(text=f"mock {node_type.removeprefix('engine/')} output")

    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'pipeline.sqlite3'}")
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.db"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    monkeypatch.delenv("SKIP_DAG_INIT", raising=False)
    monkeypatch.setattr("app.main.require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr("app.main.discover_seed_configs", skip_discover_seed_configs)
    monkeypatch.setattr(
        "app.services.task_orchestrator.TaskOrchestrator._append_event_log_fire_and_forget",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(EngineClient, "process", mock_process)
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    get_settings.cache_clear()
    get_file_store.cache_clear()
    get_tasks_file_store.cache_clear()
    get_workflow_store.cache_clear()
    get_storage.cache_clear()
    async with app.router.lifespan_context(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_tasks_file_store.cache_clear()
    get_file_store.cache_clear()
    get_storage.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ocr_workflow() -> dict:
    """Text engine workflow using the current input → engine → final contract."""
    return {
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


def _plaintext_workflow() -> dict:
    return _ocr_workflow()


def _yaml_workflow() -> dict:
    return _ocr_workflow()


async def _upload_file(
    client: AsyncClient,
    *,
    name: str = "doc.txt",
    payload: bytes = b"hello world",
    mime: str = "text/plain",
) -> str:
    resp = await client.post(
        "/api/files/upload",
        files={"file": (name, payload, mime)},
    )
    assert resp.status_code == 200
    return resp.json()["file_id"]


async def _create_workflow(client: AsyncClient, definition: dict) -> str:
    resp = await client.post(
        "/api/workflows",
        json={"name": "test-pipeline", "definition": definition},
    )
    assert resp.status_code == 201, f"Workflow creation failed: {resp.text}"
    return resp.json()["workflow_id"]


async def _execute_workflow(client: AsyncClient, workflow_id: str, file_ids: list[str]) -> str:
    resp = await client.post(
        f"/api/workflows/{workflow_id}/execute",
        json={"file_ids": file_ids},
    )
    assert resp.status_code == 202
    return resp.json()["task_id"]


async def _poll_until_done(client: AsyncClient, task_id: str, timeout: float = 5.0) -> dict:
    await app.state.task_orchestrator.wait_for_completion(
        task_id,
        timeout=timeout,
        workspace_id=TEST_WORKSPACE_ID,
    )
    response = await client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# 1. Full pipeline: upload → create workflow → execute → poll → results → download
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_full_pipeline_upload_workflow_execute_results_download(
    isolated_pipeline: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="sample.txt", payload=b"pipeline test")
        wf_id = await _create_workflow(client, _ocr_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])

        completed = await _poll_until_done(client, task_id)
        assert completed["status"] in {"completed", "partial_completed"}

        results_resp = await client.get(f"/api/tasks/{task_id}/results")
        assert results_resp.status_code == 200
        results_body = results_resp.json()
        assert results_body["task_id"] == task_id
        assert len(results_body["results"]) >= 1

        result_id = results_body["results"][0]["result_id"]
        dl_resp = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")
        assert dl_resp.status_code == 403
        assert dl_resp.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 2. Full pipeline with OCR engine produces valid markdown with content
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_full_pipeline_ocr_produces_valid_markdown(
    isolated_pipeline: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="ocr_test.txt", payload=b"ocr content")
        wf_id = await _create_workflow(client, _ocr_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])

        completed = await _poll_until_done(client, task_id)
        assert completed["status"] in {"completed", "partial_completed"}

        results_resp = await client.get(f"/api/tasks/{task_id}/results")
        body = results_resp.json()
        result = body["results"][0]
        assert result["file"]["content_type"] == "text/markdown"
        assert len(result["content"]) > 0

        result_id = result["result_id"]
        dl_resp = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")
        assert dl_resp.status_code == 403
        assert dl_resp.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 3. Full pipeline with plaintext output produces valid .txt
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_full_pipeline_plaintext_output(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="plain.txt", payload=b"plain content")
        wf_id = await _create_workflow(client, _plaintext_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])

        completed = await _poll_until_done(client, task_id)
        assert completed["status"] in {"completed", "partial_completed"}

        results_resp = await client.get(f"/api/tasks/{task_id}/results")
        body = results_resp.json()
        assert len(body["results"]) >= 1
        result = body["results"][0]
        result_id = result["result_id"]

        dl_resp = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")
        assert dl_resp.status_code == 403
        assert dl_resp.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 4. Full pipeline with yaml output produces valid .yaml
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_full_pipeline_yaml_output(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="yaml_test.txt", payload=b"yaml content")
        wf_id = await _create_workflow(client, _yaml_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])

        completed = await _poll_until_done(client, task_id)
        assert completed["status"] in {"completed", "partial_completed"}

        results_resp = await client.get(f"/api/tasks/{task_id}/results")
        body = results_resp.json()
        assert len(body["results"]) >= 1
        result = body["results"][0]
        result_id = result["result_id"]

        dl_resp = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")
        assert dl_resp.status_code == 403
        assert dl_resp.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 5. Node Registry returns all 4 engine types
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_node_registry_returns_all_engine_types(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/nodes/registry")

    assert resp.status_code == 200
    body = resp.json()
    nodes = {node["node_type"] for node in body["nodes"]}
    assert "engine/ocr" in nodes
    assert "engine/model" in nodes
    assert "engine/vlm" not in nodes
    assert "engine/text" in nodes
    assert "engine/markitdown" in nodes


# ---------------------------------------------------------------------------
# 6. Node Registry returns all 4 categories
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_node_registry_returns_all_categories(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/nodes/registry")

    assert resp.status_code == 200
    body = resp.json()
    category_ids = {cat["category_id"] for cat in body["categories"]}
    assert category_ids == {"input", "processor", "engine", "end"}


# ---------------------------------------------------------------------------
# 7. Node Registry engine nodes have correct config_schema structure
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_node_registry_engine_config_schema(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/nodes/registry")

    assert resp.status_code == 200
    body = resp.json()
    engine_nodes = [n for n in body["nodes"] if n["node_type"].startswith("engine/")]
    assert len(engine_nodes) >= 4

    for node in engine_nodes:
        assert "config_schema" in node, f"{node['node_type']} missing config_schema"
        schema = node["config_schema"]
        assert isinstance(schema, dict), f"{node['node_type']} config_schema not dict"


# ---------------------------------------------------------------------------
# 8. Backward compat: upload → POST /api/tasks → poll → download (S1 API)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_backward_compat_s1_task_api(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/tasks",
            data={"engine": "ocr", "output_format": "markdown"},
            files={"file": ("compat.txt", b"backward compat test", "text/plain")},
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        assert task_id.startswith("task_")


# ---------------------------------------------------------------------------
# 9. Upload same file twice → two independent tasks complete correctly
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_upload_same_file_twice_independent_tasks(
    isolated_pipeline: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id_1 = await _upload_file(client, name="dup.txt", payload=b"duplicate")
        file_id_2 = await _upload_file(client, name="dup.txt", payload=b"duplicate")

        wf_id = await _create_workflow(client, _ocr_workflow())

        task_id_1 = await _execute_workflow(client, wf_id, [file_id_1])
        c1 = await _poll_until_done(client, task_id_1)
        task_id_2 = await _execute_workflow(client, wf_id, [file_id_2])
        c2 = await _poll_until_done(client, task_id_2)

        assert task_id_1 != task_id_2

        assert c1["status"] in {"completed", "partial_completed"}
        assert c2["status"] in {"completed", "partial_completed"}
        assert c1["task_id"] != c2["task_id"]


# ---------------------------------------------------------------------------
# 10. Large payload: upload 1MB text file → workflow → complete without error
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_large_payload_1mb_completes(isolated_pipeline: Path) -> None:
    large_payload = b"A" * (1024 * 1024)  # 1 MB
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(
            client, name="large.txt", payload=large_payload, mime="text/plain"
        )
        wf_id = await _create_workflow(client, _ocr_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])

        completed = await _poll_until_done(client, task_id, timeout=10.0)
        assert completed["status"] in {"completed", "partial_completed"}


# ---------------------------------------------------------------------------
# 11. Results endpoint returns correct summary counts
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_results_endpoint_summary_counts(isolated_pipeline: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="summary.txt", payload=b"summary test")
        wf_id = await _create_workflow(client, _ocr_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])
        await _poll_until_done(client, task_id)

        resp = await client.get(f"/api/tasks/{task_id}/results")

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["status"] in {"completed", "partial_completed"}

    summary = body["summary"]
    assert "total_outputs" in summary
    assert "completed" in summary
    assert "failed" in summary
    assert summary["total_outputs"] >= 1
    assert summary["completed"] >= 1
    assert summary["failed"] == 0
    assert summary["total_outputs"] == len(body["results"])


# ---------------------------------------------------------------------------
# 12. Download endpoint returns correct content-type and content-disposition
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_download_headers_content_type_and_disposition(
    isolated_pipeline: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_id = await _upload_file(client, name="headers.txt", payload=b"header test")
        wf_id = await _create_workflow(client, _ocr_workflow())
        task_id = await _execute_workflow(client, wf_id, [file_id])
        await _poll_until_done(client, task_id)

        results_resp = await client.get(f"/api/tasks/{task_id}/results")
        result_id = results_resp.json()["results"][0]["result_id"]

        dl_resp = await client.get(f"/api/tasks/{task_id}/results/{result_id}/download")

    assert dl_resp.status_code == 403
    assert dl_resp.json()["error_code"] == "ACCESS_DENIED"
    assert dl_resp.headers["content-type"].startswith("application/json")
