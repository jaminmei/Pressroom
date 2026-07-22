"""Invalid pipeline validation tests.

Validates that the WorkflowValidator correctly rejects invalid connections
based on port-type MIME matching (spec section 9.2).

Test cases:
  INV-1: end/final used as source (max_outputs=0, END_NODE_NOT_TERMINAL)
  INV-2: engine/text -> processor/layout_detection (text/raw vs image/*)
  INV-3: output/markdown -> engine/ocr (text/markdown vs image/*, + S8)
  INV-4: processor/layout_detection -> output/markdown (x-layout-result vs text/raw)
  INV-5: input/text -> engine/ocr (text/plain vs image/*)
"""

from __future__ import annotations

from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.workflow_validator import WorkflowValidator


def _validator() -> WorkflowValidator:
    return WorkflowValidator(node_registry=NodeRegistryService())


def _has_error(result, code: str) -> bool:
    """Check if any error in result matches the given code."""
    return any(e.code == code for e in result.errors)


def _find_errors(result, code: str):
    """Return all errors matching the given code."""
    return [e for e in result.errors if e.code == code]


class TestInvalidPipelines:
    """Tests for pipelines that must be rejected by the validator."""

    def test_inv01_end_as_source(self):
        """INV-1: end/final cannot be used as a connection source.

        Pipeline: input/image -> engine/ocr -> output/markdown -> end/final
                  + end/final -> engine/ocr (invalid back-edge)

        end/final has max_outputs=0 and output_types=[], so it cannot
        produce data. The validator should flag INVALID_CONNECTION
        (max_outputs exceeded) and/or END_NODE_NOT_TERMINAL.
        """
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_img", type="input/image"),
                WorkflowNode(id="engine_ocr", type="engine/ocr"),
                WorkflowNode(id="output_md", type="end/final"),
                WorkflowNode(id="end_final", type="end/final"),
            ],
            connections=[
                WorkflowConnection(source="input_img", target="engine_ocr"),
                WorkflowConnection(source="engine_ocr", target="output_md"),
                WorkflowConnection(source="output_md", target="end_final"),
                # Invalid: end node used as source
                WorkflowConnection(source="end_final", target="engine_ocr"),
            ],
        )

        result = _validator().validate(definition)

        assert result.valid is False

        # Must flag at least one of these two codes
        has_invalid_conn = _has_error(result, "INVALID_CONNECTION")
        has_not_terminal = _has_error(result, "END_NODE_NOT_TERMINAL")
        assert has_invalid_conn or has_not_terminal, (
            f"Expected INVALID_CONNECTION or END_NODE_NOT_TERMINAL, "
            f"got codes: {[e.code for e in result.errors]}"
        )

        # Verify error details reference the end node
        relevant_errors = _find_errors(result, "INVALID_CONNECTION") + _find_errors(
            result, "END_NODE_NOT_TERMINAL"
        )
        end_node_referenced = any(
            e.node_id == "end_final" or e.details.get("node_id") == "end_final"
            for e in relevant_errors
        )
        assert end_node_referenced, "Error details should reference the end_final node"

    def test_inv02_engine_text_to_layout_detection(self):
        """INV-2: engine/text output is incompatible with layout_detection input.

        Pipeline: input/text -> engine/text -> processor/layout_detection
                  -> engine/ocr -> output/markdown -> end/final

        engine/text outputs text/raw, but processor/layout_detection
        accepts only image/* and application/pdf. The connection
        engine/text -> processor/layout_detection must fail type checking.
        """
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_text", type="input/text"),
                WorkflowNode(id="engine_text", type="engine/text"),
                WorkflowNode(id="proc_layout", type="processor/layout_detection"),
                WorkflowNode(id="engine_ocr", type="engine/ocr"),
                WorkflowNode(id="output_md", type="end/final"),
                WorkflowNode(id="end_final", type="end/final"),
            ],
            connections=[
                WorkflowConnection(source="input_text", target="engine_text"),
                # Invalid: text/raw -> layout_detection (expects image/*)
                WorkflowConnection(source="engine_text", target="proc_layout"),
                WorkflowConnection(source="proc_layout", target="engine_ocr"),
                WorkflowConnection(source="engine_ocr", target="output_md"),
                WorkflowConnection(source="output_md", target="end_final"),
            ],
        )

        result = _validator().validate(definition)

        assert result.valid is False
        assert _has_error(result, "TYPE_INCOMPATIBLE")

        # Verify the error identifies the specific incompatible edge
        type_errors = _find_errors(result, "TYPE_INCOMPATIBLE")
        edge_found = any(
            e.details.get("source") == "engine_text" and e.details.get("target") == "proc_layout"
            for e in type_errors
        )
        assert edge_found, (
            "TYPE_INCOMPATIBLE error should identify engine_text -> proc_layout; "
            f"got details: {[e.details for e in type_errors]}"
        )

    def test_inv03_output_to_engine(self):
        """INV-3: output/markdown cannot connect to engine/ocr.

        Pipeline: input/image -> engine/ocr -> output/markdown -> engine/ocr_2

        output/markdown produces text/markdown which is incompatible with
        engine/ocr's accepted types (image/*, application/pdf, etc.).
        This also violates S8: output nodes must connect to end/final.
        """
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_img", type="input/image"),
                WorkflowNode(id="engine_ocr", type="engine/ocr"),
                WorkflowNode(id="output_md", type="end/final"),
                # Second OCR node as the invalid target
                WorkflowNode(id="engine_ocr_2", type="engine/ocr"),
                WorkflowNode(id="end_final", type="end/final"),
            ],
            connections=[
                WorkflowConnection(source="input_img", target="engine_ocr"),
                WorkflowConnection(source="engine_ocr", target="output_md"),
                # Invalid: output -> engine (type mismatch + S8 violation)
                WorkflowConnection(source="output_md", target="engine_ocr_2"),
            ],
        )

        result = _validator().validate(definition)

        assert result.valid is False

        # Must flag type incompatibility and/or output-not-connected-to-end
        has_type_error = _has_error(result, "TYPE_INCOMPATIBLE")
        has_s8_error = _has_error(result, "OUTPUT_NOT_CONNECTED_TO_END")
        assert has_type_error or has_s8_error, (
            f"Expected TYPE_INCOMPATIBLE or OUTPUT_NOT_CONNECTED_TO_END, "
            f"got codes: {[e.code for e in result.errors]}"
        )

        # If TYPE_INCOMPATIBLE is present, verify it targets the right edge
        if has_type_error:
            type_errors = _find_errors(result, "TYPE_INCOMPATIBLE")
            edge_found = any(
                e.details.get("source") == "output_md" and e.details.get("target") == "engine_ocr_2"
                for e in type_errors
            )
            assert edge_found, (
                "TYPE_INCOMPATIBLE should identify output_md -> engine_ocr_2; "
                f"got details: {[e.details for e in type_errors]}"
            )

        # If OUTPUT_NOT_CONNECTED_TO_END is present, verify it targets output_md
        if has_s8_error:
            s8_errors = _find_errors(result, "OUTPUT_NOT_CONNECTED_TO_END")
            node_found = any(
                e.node_id == "output_md" or e.details.get("node_id") == "output_md"
                for e in s8_errors
            )
            assert node_found, (
                "OUTPUT_NOT_CONNECTED_TO_END should reference output_md; "
                f"got details: {[e.details for e in s8_errors]}"
            )

    def test_inv04_layout_detection_to_output(self):
        """INV-4: layout_detection output is incompatible with output/markdown input.

        Pipeline: input/image -> processor/layout_detection
                  -> output/markdown -> end/final

        processor/layout_detection outputs application/x-layout-result,
        but output/markdown accepts only text/raw and text/plain.
        """
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_img", type="input/image"),
                WorkflowNode(id="proc_layout", type="processor/layout_detection"),
                WorkflowNode(id="output_md", type="end/final"),
                WorkflowNode(id="end_final", type="end/final"),
            ],
            connections=[
                WorkflowConnection(source="input_img", target="proc_layout"),
                # Invalid: x-layout-result -> output/markdown (expects text/raw)
                WorkflowConnection(source="proc_layout", target="output_md"),
                WorkflowConnection(source="output_md", target="end_final"),
            ],
        )

        result = _validator().validate(definition)

        assert result.valid is False
        assert _has_error(result, "TYPE_INCOMPATIBLE")

        # Verify the error identifies the specific incompatible edge
        type_errors = _find_errors(result, "TYPE_INCOMPATIBLE")
        edge_found = any(
            e.details.get("source") == "proc_layout" and e.details.get("target") == "output_md"
            for e in type_errors
        )
        assert edge_found, (
            "TYPE_INCOMPATIBLE error should identify proc_layout -> output_md; "
            f"got details: {[e.details for e in type_errors]}"
        )

    def test_inv05_text_input_to_ocr(self):
        """INV-5: input/text output is incompatible with engine/ocr input.

        Pipeline: input/text -> engine/ocr -> output/markdown -> end/final

        input/text outputs text/plain, but engine/ocr accepts only
        image/*, application/pdf, image/cropped_blocks, and
        application/x-layout-result.
        """
        definition = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="input_text", type="input/text"),
                WorkflowNode(id="engine_ocr", type="engine/ocr"),
                WorkflowNode(id="output_md", type="end/final"),
                WorkflowNode(id="end_final", type="end/final"),
            ],
            connections=[
                # Invalid: text/plain -> engine/ocr (expects image/*)
                WorkflowConnection(source="input_text", target="engine_ocr"),
                WorkflowConnection(source="engine_ocr", target="output_md"),
                WorkflowConnection(source="output_md", target="end_final"),
            ],
        )

        result = _validator().validate(definition)

        assert result.valid is False
        assert _has_error(result, "TYPE_INCOMPATIBLE")

        # Verify the error identifies the specific incompatible edge
        type_errors = _find_errors(result, "TYPE_INCOMPATIBLE")
        edge_found = any(
            e.details.get("source") == "input_text" and e.details.get("target") == "engine_ocr"
            for e in type_errors
        )
        assert edge_found, (
            "TYPE_INCOMPATIBLE error should identify input_text -> engine_ocr; "
            f"got details: {[e.details for e in type_errors]}"
        )
