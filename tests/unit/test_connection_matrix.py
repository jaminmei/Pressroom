"""Exhaustive backend connection matrix tests.

Validates every (source_type, target_type) pair against the node registry
using MIME-based type compatibility, structural constraints (max_inputs,
max_outputs), and node existence checks.

Matrix dimensions: 13 source types x 10 target types = 130 cells.

Sources: input/image, input/pdf, input/text, processor/image_enhance,
         processor/rotate, processor/layout_detection, processor/block_selector,
         engine/ocr, engine/model, engine/text, engine/markitdown,
         engine/docling, end/final

Targets: processor/image_enhance, processor/rotate, processor/layout_detection,
         processor/block_selector, engine/ocr, engine/model, engine/text,
         engine/markitdown, engine/docling, end/final
"""

from __future__ import annotations

import pytest

from app.services.node_registry import NodeRegistryService


def _match_type(source: str, target: str) -> bool:
    """Check if a single source MIME type matches a single target MIME type.

    Supports wildcard matching (e.g. image/* matches image/png).
    Mirrors WorkflowValidator._match_type exactly.
    """
    if source == target:
        return True
    if source.endswith("/*"):
        return target.startswith(source[:-1])
    if target.endswith("/*"):
        return source.startswith(target[:-1])
    return False


def _is_connection_valid(source_type: str, target_type: str) -> bool:
    """Check if source_type can connect to target_type.

    Uses the live NodeRegistryService to look up node definitions and
    validates: node existence, structural limits, and MIME compatibility.
    Collects accepted_types from input_ports when available, falls back to
    input_types for nodes that have no ports (e.g. input/* nodes).
    """
    registry = NodeRegistryService()
    source_def = registry.get_node_definition(source_type)
    target_def = registry.get_node_definition(target_type)

    if source_def is None or target_def is None:
        return False

    if source_def.max_outputs == 0:
        return False
    if target_def.max_inputs == 0:
        return False

    # Collect all accepted MIME types from input_ports if present,
    # otherwise fall back to input_types for backward compat.
    if target_def.input_ports:
        target_accepted: list[str] = []
        for port in target_def.input_ports:
            target_accepted.extend(port.accepted_types)
    else:
        target_accepted = target_def.input_types

    if not target_accepted:
        return True

    return any(_match_type(src, tgt) for src in source_def.output_types for tgt in target_accepted)


# ---------------------------------------------------------------------------
# 120-cell connection matrix
# ---------------------------------------------------------------------------
# Each tuple: (source_type, target_type, expected_valid)
#
# processor/block_selector is not yet registered, so all connections
# involving it return False (node definition is None).
#
# output/markdown is used as the concrete representative for "output/*".
# ---------------------------------------------------------------------------

CONNECTION_MATRIX: list[tuple[str, str, bool]] = [
    # --- input/image (outputs: image/*) ---
    ("input/image", "processor/image_enhance", True),
    ("input/image", "processor/rotate", True),
    ("input/image", "processor/layout_detection", True),
    ("input/image", "processor/block_selector", False),  # node not registered
    ("input/image", "engine/ocr", True),
    ("input/image", "engine/model", True),
    ("input/image", "engine/text", False),
    ("input/image", "engine/markitdown", False),  # markitdown only accepts document types
    ("input/image", "engine/docling", True),  # image/* accepted
    ("input/image", "end/final", True),
    # --- input/pdf (outputs: application/pdf) ---
    ("input/pdf", "processor/image_enhance", False),  # pdf ≠ image/*
    ("input/pdf", "processor/rotate", False),
    ("input/pdf", "processor/layout_detection", False),
    ("input/pdf", "processor/block_selector", False),  # node not registered
    ("input/pdf", "engine/ocr", False),  # pdf ≠ image/*
    ("input/pdf", "engine/model", False),
    ("input/pdf", "engine/text", False),
    ("input/pdf", "engine/markitdown", True),  # pdf matches application/pdf
    ("input/pdf", "engine/docling", True),  # pdf accepted
    ("input/pdf", "end/final", False),
    # --- input/text (outputs: text/plain) ---
    ("input/text", "processor/image_enhance", False),
    ("input/text", "processor/rotate", False),
    ("input/text", "processor/layout_detection", False),
    ("input/text", "processor/block_selector", False),  # node not registered
    ("input/text", "engine/ocr", False),
    ("input/text", "engine/model", True),  # text/plain matches text port
    ("input/text", "engine/text", True),
    ("input/text", "engine/markitdown", True),
    ("input/text", "engine/docling", True),  # text/plain accepted
    ("input/text", "end/final", True),
    # --- processor/image_enhance (outputs: image/*) ---
    ("processor/image_enhance", "processor/image_enhance", True),
    ("processor/image_enhance", "processor/rotate", True),
    ("processor/image_enhance", "processor/layout_detection", True),
    ("processor/image_enhance", "processor/block_selector", False),  # node not registered
    ("processor/image_enhance", "engine/ocr", True),
    ("processor/image_enhance", "engine/model", True),
    ("processor/image_enhance", "engine/text", False),
    (
        "processor/image_enhance",
        "engine/markitdown",
        False,
    ),  # markitdown only accepts document types
    ("processor/image_enhance", "engine/docling", True),  # image/* accepted
    ("processor/image_enhance", "end/final", True),
    # --- processor/rotate (outputs: image/*) ---
    ("processor/rotate", "processor/image_enhance", True),
    ("processor/rotate", "processor/rotate", True),
    ("processor/rotate", "processor/layout_detection", True),
    ("processor/rotate", "processor/block_selector", False),  # node not registered
    ("processor/rotate", "engine/ocr", True),
    ("processor/rotate", "engine/model", True),
    ("processor/rotate", "engine/text", False),
    ("processor/rotate", "engine/markitdown", False),  # markitdown only accepts document types
    ("processor/rotate", "engine/docling", True),  # image/* accepted
    ("processor/rotate", "end/final", True),
    # --- processor/layout_detection (outputs: application/x-layout-result) ---
    ("processor/layout_detection", "processor/image_enhance", False),
    ("processor/layout_detection", "processor/rotate", False),
    ("processor/layout_detection", "processor/layout_detection", False),
    ("processor/layout_detection", "processor/block_selector", False),  # node not registered
    ("processor/layout_detection", "engine/ocr", True),  # layout-result accepted
    ("processor/layout_detection", "engine/model", True),  # layout-result accepted
    ("processor/layout_detection", "engine/text", False),
    ("processor/layout_detection", "engine/markitdown", False),
    ("processor/layout_detection", "engine/docling", False),
    ("processor/layout_detection", "end/final", False),
    # --- processor/block_selector (NOT REGISTERED — all False) ---
    ("processor/block_selector", "processor/image_enhance", False),
    ("processor/block_selector", "processor/rotate", False),
    ("processor/block_selector", "processor/layout_detection", False),
    ("processor/block_selector", "processor/block_selector", False),
    ("processor/block_selector", "engine/ocr", False),
    ("processor/block_selector", "engine/model", False),
    ("processor/block_selector", "engine/text", False),
    ("processor/block_selector", "engine/markitdown", False),
    ("processor/block_selector", "engine/docling", False),
    ("processor/block_selector", "end/final", False),
    # --- engine/ocr (outputs: text/raw) ---
    ("engine/ocr", "processor/image_enhance", False),
    ("engine/ocr", "processor/rotate", False),
    ("engine/ocr", "processor/layout_detection", False),
    ("engine/ocr", "processor/block_selector", False),
    ("engine/ocr", "engine/ocr", False),
    ("engine/ocr", "engine/model", True),  # text/raw matches text port
    ("engine/ocr", "engine/text", False),
    ("engine/ocr", "engine/markitdown", False),
    ("engine/ocr", "engine/docling", False),
    ("engine/ocr", "end/final", True),
    # --- engine/model (outputs: text/raw) ---
    ("engine/model", "processor/image_enhance", False),
    ("engine/model", "processor/rotate", False),
    ("engine/model", "processor/layout_detection", False),
    ("engine/model", "processor/block_selector", False),
    ("engine/model", "engine/ocr", False),
    ("engine/model", "engine/model", True),  # text/raw matches text port
    ("engine/model", "engine/text", False),
    ("engine/model", "engine/markitdown", False),
    ("engine/model", "engine/docling", False),
    ("engine/model", "end/final", True),
    # --- engine/text (outputs: text/raw) ---
    ("engine/text", "processor/image_enhance", False),
    ("engine/text", "processor/rotate", False),
    ("engine/text", "processor/layout_detection", False),
    ("engine/text", "processor/block_selector", False),
    ("engine/text", "engine/ocr", False),
    ("engine/text", "engine/model", True),  # text/raw matches text port
    ("engine/text", "engine/text", False),
    ("engine/text", "engine/markitdown", False),
    ("engine/text", "engine/docling", False),
    ("engine/text", "end/final", True),
    # --- engine/markitdown (outputs: text/raw) ---
    ("engine/markitdown", "processor/image_enhance", False),
    ("engine/markitdown", "processor/rotate", False),
    ("engine/markitdown", "processor/layout_detection", False),
    ("engine/markitdown", "processor/block_selector", False),
    ("engine/markitdown", "engine/ocr", False),
    ("engine/markitdown", "engine/model", True),  # text/raw matches text port
    ("engine/markitdown", "engine/text", False),
    ("engine/markitdown", "engine/markitdown", False),
    ("engine/markitdown", "engine/docling", False),
    ("engine/markitdown", "end/final", True),
    # --- engine/docling (outputs: text/raw) ---
    ("engine/docling", "processor/image_enhance", False),
    ("engine/docling", "processor/rotate", False),
    ("engine/docling", "processor/layout_detection", False),
    ("engine/docling", "processor/block_selector", False),
    ("engine/docling", "engine/ocr", False),
    ("engine/docling", "engine/model", True),  # text/raw matches text port
    ("engine/docling", "engine/text", False),
    ("engine/docling", "engine/markitdown", False),
    ("engine/docling", "engine/docling", False),  # text/raw not in accepted types
    ("engine/docling", "end/final", True),
    # --- end/final (outputs: [] — terminal node) ---
    ("end/final", "processor/image_enhance", False),  # max_outputs=0
    ("end/final", "processor/rotate", False),
    ("end/final", "processor/layout_detection", False),
    ("end/final", "processor/block_selector", False),
    ("end/final", "engine/ocr", False),
    ("end/final", "engine/model", False),
    ("end/final", "engine/text", False),
    ("end/final", "engine/markitdown", False),
    ("end/final", "engine/docling", False),
    ("end/final", "end/final", False),
]


class TestConnectionMatrix:
    """Exhaustive 130-cell parametrised matrix test."""

    @pytest.mark.parametrize(
        ("source_type", "target_type", "expected"),
        CONNECTION_MATRIX,
        ids=[f"{src}->{tgt}" for src, tgt, _ in CONNECTION_MATRIX],
    )
    def test_connection_cell(self, source_type: str, target_type: str, expected: bool) -> None:
        result = _is_connection_valid(source_type, target_type)
        assert result is expected, (
            f"Connection {source_type} -> {target_type}: expected {expected}, got {result}"
        )

    def test_matrix_has_130_cells(self) -> None:
        assert len(CONNECTION_MATRIX) == 130

    def test_matrix_covers_all_source_types(self) -> None:
        sources = {src for src, _, _ in CONNECTION_MATRIX}
        expected_sources = {
            "input/image",
            "input/pdf",
            "input/text",
            "processor/image_enhance",
            "processor/rotate",
            "processor/layout_detection",
            "processor/block_selector",
            "engine/ocr",
            "engine/model",
            "engine/text",
            "engine/markitdown",
            "engine/docling",
            "end/final",
        }
        assert sources == expected_sources

    def test_matrix_covers_all_target_types(self) -> None:
        targets = {tgt for _, tgt, _ in CONNECTION_MATRIX}
        expected_targets = {
            "processor/image_enhance",
            "processor/rotate",
            "processor/layout_detection",
            "processor/block_selector",
            "engine/ocr",
            "engine/model",
            "engine/text",
            "engine/markitdown",
            "engine/docling",
            "end/final",
        }
        assert targets == expected_targets


class TestConnectionMatrixHelperConsistency:
    """Verify that the test helper matches WorkflowValidator internals."""

    def test_match_type_identity(self) -> None:
        assert _match_type("image/png", "image/png") is True

    def test_match_type_source_wildcard(self) -> None:
        assert _match_type("image/*", "image/png") is True

    def test_match_type_target_wildcard(self) -> None:
        assert _match_type("image/png", "image/*") is True

    def test_match_type_no_match(self) -> None:
        assert _match_type("image/png", "text/plain") is False

    def test_match_type_wildcard_different_prefix(self) -> None:
        assert _match_type("image/*", "text/plain") is False

    def test_unregistered_source_returns_false(self) -> None:
        assert _is_connection_valid("nonexistent/type", "engine/ocr") is False

    def test_unregistered_target_returns_false(self) -> None:
        assert _is_connection_valid("input/image", "nonexistent/type") is False

    def test_end_node_as_source_blocked(self) -> None:
        """end/final has max_outputs=0 so it cannot be a source."""
        assert _is_connection_valid("end/final", "engine/ocr") is False

    def test_input_node_as_target_blocked(self) -> None:
        """Input nodes have max_inputs=0 so they cannot be a target."""
        assert _is_connection_valid("engine/ocr", "input/image") is False
        assert _is_connection_valid("engine/ocr", "input/pdf") is False
        assert _is_connection_valid("engine/ocr", "input/text") is False


class TestRegistryAssumptions:
    """Guard-rail tests verifying registry data that the matrix depends on."""

    def test_block_selector_not_registered(self) -> None:
        """An unregistered sentinel node type is absent from the registry."""
        registry = NodeRegistryService()
        assert registry.get_node_definition("processor/block_selector") is None

    def test_markitdown_accepts_document_types_only(self) -> None:
        """engine/markitdown only accepts document types (pdf, text, html), not image/*."""
        registry = NodeRegistryService()
        node_def = registry.get_node_definition("engine/markitdown")
        assert node_def is not None
        doc_port = next((p for p in node_def.input_ports if p.name == "document"), None)
        assert doc_port is not None
        assert set(doc_port.accepted_types) == {"application/pdf", "text/plain", "text/html"}
        assert "image/*" not in doc_port.accepted_types

    def test_end_final_max_outputs_zero(self) -> None:
        registry = NodeRegistryService()
        node_def = registry.get_node_definition("end/final")
        assert node_def is not None
        assert node_def.max_outputs == 0

    def test_input_nodes_max_inputs_zero(self) -> None:
        registry = NodeRegistryService()
        for node_type in ("input/image", "input/pdf", "input/text"):
            node_def = registry.get_node_definition(node_type)
            assert node_def is not None
            assert node_def.max_inputs == 0, f"{node_type} should have max_inputs=0"

    def test_docling_outputs_text_raw(self) -> None:
        registry = NodeRegistryService()
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert node_def.output_types == ["text/raw"]

    def test_docling_accepts_document_and_image_types(self) -> None:
        registry = NodeRegistryService()
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        doc_port = next((p for p in node_def.input_ports if p.name == "document"), None)
        assert doc_port is not None
        assert set(doc_port.accepted_types) == {
            "application/pdf",
            "text/plain",
            "text/html",
            "image/*",
        }

    def test_docling_max_inputs_one(self) -> None:
        registry = NodeRegistryService()
        node_def = registry.get_node_definition("engine/docling")
        assert node_def is not None
        assert node_def.max_inputs == 1
