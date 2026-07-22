"""Markdown output compatibility tests.

Verify text/raw output from Docling and MarkItDown engines is accepted by:
  - engine/model text input port
  - end/final input port
"""

from __future__ import annotations

import pytest

from app.services.node_registry import NodeRegistryService


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


def _get_output_types(registry: NodeRegistryService, node_type: str) -> list[str]:
    node_def = registry.get_node_definition(node_type)
    assert node_def is not None, f"{node_type} not found in registry"
    return node_def.output_types


def _get_port_accepted_types(
    registry: NodeRegistryService, node_type: str, port_name: str
) -> list[str]:
    node_def = registry.get_node_definition(node_type)
    assert node_def is not None, f"{node_type} not found in registry"
    port = next((p for p in node_def.input_ports if p.name == port_name), None)
    assert port is not None, f"Port '{port_name}' not found on {node_type}"
    return port.accepted_types


class TestDoclingTextRawCompatibility:
    """Docling outputs text/raw — verify downstream nodes accept it."""

    def test_docling_produces_text_raw(self, registry: NodeRegistryService) -> None:
        assert _get_output_types(registry, "engine/docling") == ["text/raw"]

    def test_engine_model_text_port_accepts_text_raw(self, registry: NodeRegistryService) -> None:
        accepted = _get_port_accepted_types(registry, "engine/model", "text")
        assert "text/raw" in accepted

    def test_end_final_accepts_text_raw(self, registry: NodeRegistryService) -> None:
        accepted = _get_port_accepted_types(registry, "end/final", "input")
        assert "text/raw" in accepted


class TestMarkItDownTextRawCompatibility:
    """MarkItDown outputs text/raw — verify downstream nodes accept it."""

    def test_markitdown_produces_text_raw(self, registry: NodeRegistryService) -> None:
        assert _get_output_types(registry, "engine/markitdown") == ["text/raw"]

    def test_markitdown_output_accepted_by_model_text_port(
        self, registry: NodeRegistryService
    ) -> None:
        accepted = _get_port_accepted_types(registry, "engine/model", "text")
        assert "text/raw" in accepted

    def test_markitdown_output_accepted_by_end_final(self, registry: NodeRegistryService) -> None:
        accepted = _get_port_accepted_types(registry, "end/final", "input")
        assert "text/raw" in accepted
