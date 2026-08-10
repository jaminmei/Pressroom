from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from app.api.files import get_file_store
from app.api.workflows import get_workflow_store
from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from tests.helpers.workflow_persistence_samples import (
    cloned_complex_definition_dict,
    complex_workflow_definition_dict,
)
from tests.integration.workspace_api_support import reset_db_runtime, skip_discover_seed_configs

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest_asyncio.fixture
async def isolated_workflow_persistence_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_workspace_contract: None,
) -> AsyncIterator[Path]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.sqlite3'}")
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
    reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    get_settings.cache_clear()
    get_file_store.cache_clear()
    get_workflow_store.cache_clear()
    async with app.router.lifespan_context(app):
        yield tmp_path
    get_workflow_store.cache_clear()
    get_file_store.cache_clear()
    get_settings.cache_clear()
    reset_db_runtime()


def _complex_definition() -> dict[str, object]:
    return cloned_complex_definition_dict()


@pytest.mark.anyio
async def test_unified_publish_detects_duplicate_dag_hash_and_keeps_original_snapshot(
    isolated_workflow_persistence_state: Path,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/api/workflows/publish",
            json={
                "name": "Published complex",
                "description": "v1",
                "definition": _complex_definition(),
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()["data"]

        duplicate_response = await client.post(
            "/api/workflows/publish",
            json={
                "workflow_id": created["workflow_id"],
                "name": "Published complex",
                "description": "same",
                "definition": _complex_definition(),
                "base_version": 1,
            },
        )
        assert duplicate_response.status_code == 409
        duplicate_body = duplicate_response.json()
        assert duplicate_body["error_code"] == "DUPLICATE_DAG_HASH"
        assert duplicate_body["details"]["duplicate_of_version"] == 1

        versions_response = await client.get(f"/api/workflows/{created['workflow_id']}/versions/1")
        assert versions_response.status_code == 200
        snapshot = versions_response.json()["data"]
        assert snapshot["status"] == "published"
        assert snapshot["definition"] == complex_workflow_definition_dict()


@pytest.mark.anyio
async def test_execute_uses_persisted_snapshot_without_mutating_saved_versions(
    isolated_workflow_persistence_state: Path,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_execute(definition, _execution):
        captured["before"] = deepcopy(definition.model_dump(mode="json"))
        definition.nodes[2].config["mutated_during_execute"] = True
        captured["after"] = deepcopy(definition.model_dump(mode="json"))
        return SimpleNamespace(
            task_id="task_persistence_api",
            status=SimpleNamespace(value="pending"),
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

    app.state.workflow_execution = SimpleNamespace(execute=_fake_execute)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        save_response = await client.post(
            "/api/workflows/save",
            json={
                "name": "Executable complex",
                "description": "draft",
                "definition": _complex_definition(),
            },
        )
        assert save_response.status_code == 200
        saved = save_response.json()["data"]

        upload_response = await client.post(
            "/api/files/upload",
            files={"file": ("doc.png", b"binary-image", "image/png")},
        )
        assert upload_response.status_code == 200
        file_id = upload_response.json()["file_id"]

        execute_response = await client.post(
            f"/api/workflows/{saved['id']}/execute",
            json={"file_ids": [file_id]},
        )
        assert execute_response.status_code == 202

        detail_response = await client.get(f"/api/workflows/{saved['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["definition"] == complex_workflow_definition_dict()
        assert "mutated_during_execute" not in str(detail["definition"])

        version_response = await client.get(f"/api/workflows/{saved['id']}/versions/1")
        assert version_response.status_code == 200
        version_payload = version_response.json()["data"]
        assert version_payload["definition"] == complex_workflow_definition_dict()
        assert captured["before"] == complex_workflow_definition_dict()
        assert "mutated_during_execute" in str(captured["after"])
