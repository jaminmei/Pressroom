"""Multi-engine workflow execution and output-format integration tests.

Tests each engine type (OCR, generic model, Text, MarkItDown) through the full
workflow pipeline, plus output format variants (markdown, plaintext, yaml).
All engines run in mock mode (OCR_MOCK_MODE=true).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store
from app.api.tasks import get_file_store as get_task_file_store
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

# Minimal 1x1 PNG for image-based engines
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Engine type -> compatible input node type
_ENGINE_INPUT = {
    "ocr": "input/image",
    "model": "input/image",
    "text": "input/text",
    "markitdown": "input/text",
}


@pytest_asyncio.fixture
async def isolated_env(
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
    for fn in (
        get_settings,
        get_file_store,
        get_task_file_store,
        get_workflow_store,
        get_storage,
    ):
        fn.cache_clear()
    async with app.router.lifespan_context(app):
        yield tmp_path
    for fn in (
        get_workflow_store,
        get_task_file_store,
        get_file_store,
        get_storage,
        get_settings,
    ):
        fn.cache_clear()
    reset_db_runtime()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(engine_type: str) -> dict:
    return {
        "nodes": [
            {"id": "input_1", "type": _ENGINE_INPUT[engine_type], "config": {"file": "$file_0"}},
            {"id": "engine_1", "type": f"engine/{engine_type}", "config": {}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }


def _file_for_engine(engine: str) -> tuple[str, bytes, str]:
    if engine in ("ocr", "model"):
        return f"{engine}.png", _TINY_PNG, "image/png"
    return f"{engine}.txt", b"test content", "text/plain"


async def _upload(c: AsyncClient, name: str, payload: bytes, mime: str) -> str:
    r = await c.post("/api/files/upload", files={"file": (name, payload, mime)})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


async def _create_wf(c: AsyncClient, defn: dict, name: str = "wf") -> str:
    r = await c.post("/api/workflows", json={"name": name, "definition": defn})
    assert r.status_code == 201
    return r.json()["workflow_id"]


async def _exec_wf(c: AsyncClient, wf_id: str, fids: list[str]) -> str:
    r = await c.post(f"/api/workflows/{wf_id}/execute", json={"file_ids": fids})
    assert r.status_code == 202
    return r.json()["task_id"]


async def _poll(c: AsyncClient, tid: str, timeout: float = 5.0) -> dict:
    await app.state.task_orchestrator.wait_for_completion(
        tid,
        timeout=timeout,
        workspace_id=TEST_WORKSPACE_ID,
    )
    response = await c.get(f"/api/tasks/{tid}")
    assert response.status_code == 200
    return response.json()


async def _run(c: AsyncClient, engine: str) -> dict:
    fname, payload, mime = _file_for_engine(engine)
    fid = await _upload(c, fname, payload, mime)
    wid = await _create_wf(c, _make_workflow(engine))
    tid = await _exec_wf(c, wid, [fid])
    return await _poll(c, tid)


# ---------------------------------------------------------------------------
# 1. OCR engine: upload → workflow → execute → persisted inline result
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_ocr_engine_workflow(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "ocr")
        assert done["status"] in {"completed", "partial_completed"}
        res = await c.get(f"/api/tasks/{done['task_id']}/results")
        assert res.status_code == 200
        body = res.json()
        assert len(body["results"]) >= 1
        rid = body["results"][0]["result_id"]
        dl = await c.get(f"/api/tasks/{done['task_id']}/results/{rid}/download")
        assert dl.status_code == 403
        assert dl.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 2. Text engine workflow
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_text_engine_workflow(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "text")
        assert done["status"] in {"completed", "partial_completed"}


# ---------------------------------------------------------------------------
# 3. Generic model engine workflow (mock mode)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_model_engine_workflow(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "model")
        assert done["status"] in {"completed", "partial_completed"}


# ---------------------------------------------------------------------------
# 4. MarkItDown engine workflow (mock mode)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_markitdown_engine_workflow(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "markitdown")
        assert done["status"] in {"completed", "partial_completed"}


# ---------------------------------------------------------------------------
# 5. Inline-only final output rejects a pathless download
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_final_output_rejects_pathless_download(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "text")
        assert done["status"] in {"completed", "partial_completed"}
        res = await c.get(f"/api/tasks/{done['task_id']}/results")
        rid = res.json()["results"][0]["result_id"]
        dl = await c.get(f"/api/tasks/{done['task_id']}/results/{rid}/download")
        assert dl.status_code == 403
        assert dl.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 6. Current final output includes generic engine metadata
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_final_output_has_current_engine_metadata(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, "text")
        assert done["status"] in {"completed", "partial_completed"}
        res = await c.get(f"/api/tasks/{done['task_id']}/results")
        result = res.json()["results"][0]
        assert result["engine_type"] == "text"
        assert result["node_type"] == "engine/text"
        rid = result["result_id"]
        dl = await c.get(f"/api/tasks/{done['task_id']}/results/{rid}/download")
        assert dl.status_code == 403
        assert dl.json()["error_code"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 7. Each engine produces valid (non-empty) output content
# ---------------------------------------------------------------------------
@pytest.mark.anyio
@pytest.mark.parametrize("engine", ["ocr", "model", "text", "markitdown"])
async def test_engine_produces_nonempty_content(isolated_env: Path, engine: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, engine)
        assert done["status"] in {"completed", "partial_completed"}
        res = await c.get(f"/api/tasks/{done['task_id']}/results")
        body = res.json()
        assert len(body["results"]) >= 1
        assert len(body["results"][0]["content"]) > 0


# ---------------------------------------------------------------------------
# 8. Task progress shows correct node counts
# ---------------------------------------------------------------------------
@pytest.mark.anyio
@pytest.mark.parametrize("engine", ["ocr", "model", "text", "markitdown"])
async def test_task_progress_node_counts(isolated_env: Path, engine: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, engine)
        p = done["progress"]
        assert p["total_nodes"] >= 1
        assert p["completed_nodes"] == 3
        assert p["failed_nodes"] == 0
        assert p["percentage"] == 100


# ---------------------------------------------------------------------------
# 9. Multiple sequential engine workflows complete independently
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_sequential_engine_workflows_independent(isolated_env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        results: list[dict] = []
        for eng in ["ocr", "text"]:
            fn, pay, mime = _file_for_engine(eng)
            fid = await _upload(c, fn, pay, mime)
            wid = await _create_wf(c, _make_workflow(eng), name=f"wf-{eng}")
            task_id = await _exec_wf(c, wid, [fid])
            results.append(await _poll(c, task_id))
        assert results[0]["task_id"] != results[1]["task_id"]
        for r in results:
            assert r["status"] in {"completed", "partial_completed"}


# ---------------------------------------------------------------------------
# 10. Engine selection routes to correct adapter (verify mock output text)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
@pytest.mark.parametrize(
    "engine,expected",
    [
        ("ocr", "mock ocr"),
        ("model", "mock model"),
        ("text", "mock text"),
        ("markitdown", "mock markitdown"),
    ],
)
async def test_engine_selection_routes_to_correct_adapter(
    isolated_env: Path, engine: str, expected: str
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        done = await _run(c, engine)
        assert done["status"] in {"completed", "partial_completed"}
        res = await c.get(f"/api/tasks/{done['task_id']}/results")
        content = res.json()["results"][0]["content"].lower()
        assert expected in content
