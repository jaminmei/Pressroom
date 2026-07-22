"""Tests for WorkflowValidator.check_engine_health — provider health check.

Covers:
  1. All engines healthy -> empty warnings
  2. One engine unreachable -> warning for that engine
  3. VLM engine is skipped (not checked)
  4. Empty workflow (no engine nodes) -> empty warnings
  5. Multiple engines, one unreachable -> warning only for unreachable one
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import WorkflowValidator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


@pytest.fixture()
def validator(registry: NodeRegistryService) -> WorkflowValidator:
    return WorkflowValidator(node_registry=registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed URLs for deterministic test mocking
_OCR_URL = "http://test-ocr:8002"
_TEXT_URL = "http://test-text:8004"
_MARKITDOWN_URL = "http://test-markitdown:8005"
_LAYOUT_URL = "http://test-layout:8006"
_ENHANCE_URL = "http://test-enhance:8008"
_ROTATE_URL = "http://test-rotate:8009"


def _mock_settings() -> MagicMock:
    """Return a mock Settings object with deterministic engine URLs."""
    settings = MagicMock()
    settings.ocr_engine_url = _OCR_URL
    settings.vlm_engine_url = "http://test-vlm:8003"
    settings.text_engine_url = _TEXT_URL
    settings.markitdown_engine_url = _MARKITDOWN_URL
    settings.layout_detection_engine_url = _LAYOUT_URL
    settings.image_enhancement_engine_url = _ENHANCE_URL
    settings.image_rotation_engine_url = _ROTATE_URL
    return settings


def _workflow_with_ocr() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
        ],
    )


def _workflow_with_multiple_engines() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
            WorkflowNode(id="text_1", type="engine/text", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="ocr_1"),
            WorkflowConnection(source="input_1", target="text_1"),
            WorkflowConnection(source="ocr_1", target="output_1"),
            WorkflowConnection(source="text_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
        ],
    )


def _workflow_with_vlm() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/model", config={"model": "test-vlm"}),
            WorkflowNode(id="output_1", type="end/final", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
            WorkflowConnection(source="output_1", target="end_1"),
        ],
    )


def _empty_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[],
        connections=[],
    )


# ---------------------------------------------------------------------------
# Mock factory for httpx.AsyncClient
# ---------------------------------------------------------------------------


def _make_mock_client(
    responses: dict[str, httpx.Response | Exception],
) -> MagicMock:
    """Create a mock httpx.AsyncClient.

    Args:
        responses: Maps full URLs (e.g. "http://test-ocr:8002/health") to either
                   an httpx.Response or an Exception to raise.
    """

    async def _get(url: str, **kwargs: object) -> httpx.Response:
        if url in responses:
            val = responses[url]
            if isinstance(val, Exception):
                raise val
            return val
        # Default: healthy 200
        return httpx.Response(200)

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = MagicMock(side_effect=_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckEngineHealth:
    """Tests for WorkflowValidator.check_engine_health()."""

    @pytest.mark.asyncio
    async def test_all_engines_healthy_returns_empty(self, validator: WorkflowValidator) -> None:
        """When all engine containers respond 200, no warnings are returned."""
        workflow = _workflow_with_ocr()
        mock_client = _make_mock_client(
            {
                f"{_OCR_URL}/health": httpx.Response(200),
            }
        )

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        assert warnings == []

    @pytest.mark.asyncio
    async def test_one_engine_unreachable_returns_warning(
        self, validator: WorkflowValidator
    ) -> None:
        """When an engine container is unreachable, a warning is returned for that engine type."""
        workflow = _workflow_with_ocr()
        mock_client = _make_mock_client(
            {
                f"{_OCR_URL}/health": httpx.ConnectError("Connection refused"),
            }
        )

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        assert len(warnings) == 1
        assert warnings[0].code == "ENGINE_UNREACHABLE"
        assert warnings[0].node_id == "engine/ocr"
        assert warnings[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_engine_returns_non_200_returns_warning(
        self, validator: WorkflowValidator
    ) -> None:
        """When an engine responds with a non-200 status, a warning is returned."""
        workflow = _workflow_with_ocr()
        mock_client = _make_mock_client(
            {
                f"{_OCR_URL}/health": httpx.Response(500),
            }
        )

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        assert len(warnings) == 1
        assert warnings[0].code == "ENGINE_UNREACHABLE"
        assert "HTTP 500" in warnings[0].message

    @pytest.mark.asyncio
    async def test_vlm_engine_is_skipped(self, validator: WorkflowValidator) -> None:
        """engine/model nodes are skipped because Provider tests own upstream checks."""
        workflow = _workflow_with_vlm()
        mock_client = _make_mock_client({})

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        # No HTTP calls should have been made since VLM is skipped
        mock_client.get.assert_not_called()
        assert warnings == []

    @pytest.mark.asyncio
    async def test_empty_workflow_returns_empty(self, validator: WorkflowValidator) -> None:
        """A workflow with no engine nodes produces no health-check warnings."""
        workflow = _empty_workflow()
        mock_client = _make_mock_client({})

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        mock_client.get.assert_not_called()
        assert warnings == []

    @pytest.mark.asyncio
    async def test_multiple_engines_one_unreachable(self, validator: WorkflowValidator) -> None:
        """With multiple engines, only the unreachable one produces a warning."""
        workflow = _workflow_with_multiple_engines()
        mock_client = _make_mock_client(
            {
                f"{_OCR_URL}/health": httpx.ConnectError("Connection refused"),
                f"{_TEXT_URL}/health": httpx.Response(200),
            }
        )

        with (
            patch("app.services.workflow_validator.get_settings", return_value=_mock_settings()),
            patch("app.services.workflow_validator.httpx.AsyncClient", return_value=mock_client),
        ):
            warnings = await validator.check_engine_health(workflow)

        assert len(warnings) == 1
        assert warnings[0].code == "ENGINE_UNREACHABLE"
        assert warnings[0].node_id == "engine/ocr"
