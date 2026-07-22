"""Tests for engine/docling node definition lookup and MIME compatibility.

Verifies:
  - engine/docling node definition exists and has correct fields
  - input_types include document formats and images
  - output_types is text/raw
  - text/raw is accepted by engine/model text port and end/final
"""

from __future__ import annotations

import pytest

from app.services.node_registry import NodeRegistryService


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


class TestDoclingNodeDefinition:
    def test_docling_node_definition_exists(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None

    def test_docling_display_name(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert node_def.display_name == "Docling"

    def test_docling_category_is_engine(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert node_def.category == "engine"

    def test_docling_output_types_is_text_raw(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert node_def.output_types == ["text/raw"]

    def test_docling_input_types_include_pdf(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert "application/pdf" in node_def.input_types

    def test_docling_input_types_include_text(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert "text/plain" in node_def.input_types
        assert "text/html" in node_def.input_types

    def test_docling_input_types_include_image(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert "image/*" in node_def.input_types

    def test_docling_has_document_input_port(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        port_names = [p.name for p in node_def.input_ports]
        assert "document" in port_names

    def test_docling_document_port_accepted_types(self, registry: NodeRegistryService) -> None:
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        doc_port = next(p for p in node_def.input_ports if p.name == "document")
        assert "application/pdf" in doc_port.accepted_types
        assert "text/plain" in doc_port.accepted_types
        assert "text/html" in doc_port.accepted_types
        assert "image/*" in doc_port.accepted_types


class TestDoclingMIMECompatibility:
    """Verify text/raw from docling connects to downstream nodes."""

    def test_docling_output_accepted_by_model_text_port(
        self, registry: NodeRegistryService
    ) -> None:
        model_def = registry.get_node_definition("engine/model")
        assert model_def is not None
        text_port = next(p for p in model_def.input_ports if p.name == "text")
        # text/raw should be in the accepted types of engine/model text port
        assert "text/raw" in text_port.accepted_types

    def test_docling_output_accepted_by_end_final(self, registry: NodeRegistryService) -> None:
        end_def = registry.get_node_definition("end/final")
        assert end_def is not None
        input_port = next(p for p in end_def.input_ports if p.name == "input")
        assert "text/raw" in input_port.accepted_types

    def test_docling_connects_to_markitdown_is_not_compatible(
        self, registry: NodeRegistryService
    ) -> None:
        """Docling text/raw should NOT connect to MarkItDown document port
        (MarkItDown does not accept text/raw)."""
        md_def = registry.get_node_definition("engine/markitdown")
        assert md_def is not None
        doc_port = next(p for p in md_def.input_ports if p.name == "document")
        assert "text/raw" not in doc_port.accepted_types
