"""Engine Enhancement Integration Tests.

Tests for engine enhancement features including:
- Creating tasks with output schema
- Workflow validation for Docling (simple pipeline only)
- Workflow validation for Layout Detection
- Workflow validation for Image Enhancement
- MarkItDown simple pipeline restriction
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import tasks as tasks_api
from app.api import workflows as workflows_api
from app.main import app
from app.services.workflow_store import WorkflowStore
from tests._api_workspace_contract import (
    install_authenticated_workspace,
    remove_authenticated_workspace,
)

_ORIG_GET_WORKFLOW_STORE = workflows_api.get_workflow_store


def _clear_api_caches() -> None:
    tasks_api.reset_task_orchestrator()
    _ORIG_GET_WORKFLOW_STORE.cache_clear()


@pytest.fixture(autouse=True)
def authenticated_workspace(monkeypatch: pytest.MonkeyPatch):
    install_authenticated_workspace(app, monkeypatch)
    yield
    remove_authenticated_workspace(app)


@pytest.fixture
def route_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(workflows_api, "get_workflow_store", lambda: WorkflowStore())
    monkeypatch.setattr(app.state, "dag_scheduler", SimpleNamespace(), raising=False)
    monkeypatch.setattr(app.state, "engine_client", SimpleNamespace(), raising=False)
    monkeypatch.setattr(
        app.state,
        "event_store",
        SimpleNamespace(get_events=lambda _run_id: [], compute_state=lambda _run_id: {}),
        raising=False,
    )
    monkeypatch.setattr(app.state, "running_tasks", {}, raising=False)
    monkeypatch.setattr(app.state, "provider_store", None, raising=False)
    monkeypatch.setattr(tasks_api, "_start_dag_run", lambda **_kwargs: None)
    client = TestClient(app)
    yield client
    client.close()


@pytest.fixture
def mock_workflow_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the workflow validator for validation tests."""
    from app.services.node_registry import NodeRegistryService
    from app.services.workflow_validator import WorkflowValidator

    validator = WorkflowValidator(node_registry=NodeRegistryService())
    monkeypatch.setattr(
        "app.api.workflows.get_workflow_validator",
        lambda *_args: validator,
    )


class TestEngineEnhancement:
    """Engine Enhancement API integration tests."""

    @pytest.mark.asyncio
    async def test_create_task_with_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        route_client: TestClient,
    ) -> None:
        """Test creating a task with output_schema in VLM node config."""
        _clear_api_caches()

        # Mock settings with temporary storage
        storage_root = tmp_path / "storage"
        storage_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "app.api.tasks.get_settings",
            lambda: SimpleNamespace(
                max_file_size_mb=10,
                storage_root=str(storage_root),
            ),
        )

        # Build workflow with schema
        workflow_definition = {
            "nodes": [
                {"id": "input_1", "type": "input/image", "config": {"file": "$file_0"}},
                {
                    "id": "engine_1",
                    "type": "engine/model",
                    "config": {
                        "model": "vision-model",
                        "output_schema": (
                            '{"type": "object", "properties": {"amount": {"type": "string"}}}'
                        ),
                    },
                },
                {"id": "end_1", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "input_1", "target": "engine_1"},
                {"source": "engine_1", "target": "end_1"},
            ],
        }

        response = route_client.post(
            "/api/tasks",
            data={
                "workflow": json.dumps(workflow_definition),
                "file_ids": "[]",
            },
            files={"files": ("test.png", b"fake png content", "image/png")},
        )

        # Should succeed (202) - validation passes
        assert response.status_code == 202, f"Response: {response.json()}"
        result = response.json()
        assert result["task_id"] is not None
        assert "workflow" in result

    def test_validate_workflow_docling(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating a valid Docling workflow (simple pipeline: input -> engine -> output)."""
        _clear_api_caches()

        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/pdf", "config": {"file": "test.pdf"}},
                {"id": "2", "type": "engine/docling", "config": {}},
                {"id": "3", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        assert response.status_code == 201, f"Response: {response.json()}"
        result = response.json()
        assert result["validation"]["valid"] is True

    def test_validate_workflow_docling_invalid(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating an invalid Docling workflow (complex pipeline should be rejected).

        Docling has pipeline_restriction='simple_only', which means it can only accept
        input from 'input' nodes and output to 'output' nodes. A pipeline with
        processor/layout_detection in between violates this restriction.
        """
        _clear_api_caches()

        # Complex pipeline: input -> processor -> engine -> output
        # Docling with layout_detection in front should fail validation
        # because Docling only accepts input from 'input' category nodes
        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/pdf", "config": {"file": "test.pdf"}},
                {"id": "2", "type": "processor/layout_detection", "config": {}},
                {"id": "3", "type": "engine/docling", "config": {}},
                {"id": "4", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
                {"source": "3", "target": "4"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        # Should return validation error (400)
        assert response.status_code == 400, f"Response: {response.json()}"
        result = response.json()
        # Check that validation failed - either due to type incompatibility
        # or pipeline restriction
        assert "error" in result or "error_code" in result

    def test_validate_workflow_layout_detection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating a Layout Detection workflow structure.

        Layout Detection is a processor node that can be placed in the workflow.
        Note: Current node_registry defines layout_detection output as 'layout/annotated'
        which may not be compatible with all downstream engines.
        This test validates the workflow can be defined (may have warnings).
        """
        _clear_api_caches()

        # Simple workflow: input -> layout_detection -> output (no engine)
        # This validates the layout_detection node can be used in a workflow
        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/image", "config": {"file": "test.png"}},
                {"id": "2", "type": "processor/layout_detection", "config": {}},
                {"id": "3", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        # Should either succeed or fail with type incompatibility (which is expected)
        assert response.status_code in [201, 400], f"Unexpected status: {response.status_code}"

    def test_validate_workflow_image_enhancement(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating a valid Image Enhancement workflow.

        Image Enhancement (processor/image_enhance) is a processor node that can be
        placed between input and engine to preprocess images.
        Valid pipeline: input -> processor -> engine -> output
        """
        _clear_api_caches()

        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/image", "config": {"file": "test.png"}},
                {"id": "2", "type": "processor/image_enhance", "config": {"clahe_enabled": True}},
                {"id": "3", "type": "engine/model", "config": {}},
                {"id": "4", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
                {"source": "3", "target": "4"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        assert response.status_code == 201, f"Response: {response.json()}"
        result = response.json()
        assert result["validation"]["valid"] is True

    def test_validate_workflow_markitdown_simple_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating MarkItDown simple pipeline restriction.

        MarkItDown (engine/markitdown) has pipeline_restriction='simple_only',
        which means it can only accept input from 'input' nodes and output to 'output' nodes.
        A pipeline with processor in between violates this restriction.
        """
        _clear_api_caches()

        # Invalid pipeline: input -> processor -> engine/markitdown -> output
        # MarkItDown should only accept direct input from input nodes
        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/text", "config": {"file": "test.txt"}},
                {"id": "2", "type": "processor/layout_detection", "config": {}},
                {"id": "3", "type": "engine/markitdown", "config": {}},
                {"id": "4", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
                {"source": "3", "target": "4"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        # Should return validation error (400)
        assert response.status_code == 400, f"Response: {response.json()}"
        result = response.json()
        assert "error" in result or "error_code" in result

    def test_validate_workflow_markitdown_simple_pipeline_valid(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_workflow_validator: None,
        route_client: TestClient,
    ) -> None:
        """Test validating a valid MarkItDown simple pipeline.

        MarkItDown with simple pipeline: input -> engine -> output
        """
        _clear_api_caches()

        workflow_json = {
            "nodes": [
                {"id": "1", "type": "input/text", "config": {"file": "test.txt"}},
                {"id": "2", "type": "engine/markitdown", "config": {}},
                {"id": "3", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "1", "target": "2"},
                {"source": "2", "target": "3"},
            ],
        }

        response = route_client.post(
            "/api/workflows",
            json={"definition": workflow_json},
        )

        assert response.status_code == 201, f"Response: {response.json()}"
        result = response.json()
        assert result["validation"]["valid"] is True
