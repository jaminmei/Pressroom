/**
 * Frontend mirror of the 143-cell connection matrix test.
 *
 * Validates every (source_type, target_type) pair using the frontend
 * validateConnection function. The expected results match the backend
 * test in tests/unit/test_connection_matrix.py.
 *
 * Matrix dimensions: 13 source types x 11 target types = 143 cells.
 */

import { describe, expect, it } from "vitest";

import {
  validateConnection,
  type ConnectionValidationInput,
} from "../connectionValidator";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";

// ---------------------------------------------------------------------------
// Registry mock — mirrors the real backend NodeRegistryService data
// ---------------------------------------------------------------------------

function buildFullRegistry(): Pick<NodeRegistryResponse, "nodes" | "connection_rules"> {
  return {
    nodes: [
      {
        node_type: "input/image",
        display_name: "Image Input",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["image/*"],
        max_inputs: 0,
        max_outputs: -1,
      },
      {
        node_type: "input/pdf",
        display_name: "PDF Input",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["application/pdf", "image/*"],
        max_inputs: 0,
        max_outputs: -1,
      },
      {
        node_type: "input/text",
        display_name: "Text Input",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["text/plain"],
        max_inputs: 0,
        max_outputs: -1,
      },
      {
        node_type: "processor/image_enhance",
        display_name: "Image Enhance",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_types: ["image/*"],
        output_types: ["image/*"],
        max_inputs: 1,
        max_outputs: -1,
      },
      {
        node_type: "processor/rotate",
        display_name: "Rotate",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_types: ["image/*"],
        output_types: ["image/*"],
        max_inputs: 1,
        max_outputs: -1,
      },
      {
        node_type: "processor/layout_detection",
        display_name: "Layout Detection",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_types: ["image/*", "application/pdf"],
        output_types: ["application/x-layout-result"],
        max_inputs: 1,
        max_outputs: -1,
      },
      {
        node_type: "engine/ocr",
        display_name: "OCR",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: [
          "image/*",
          "application/pdf",
          "image/cropped_blocks",
          "application/x-layout-result",
        ],
        output_types: ["text/raw"],
        max_inputs: -1,
        max_outputs: -1,
      },
      {
        node_type: "engine/model",
        display_name: "Model",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: [
          "image/*",
          "image/cropped_blocks",
          "text/raw",
          "text/plain",
          "application/x-layout-result",
        ],
        output_types: ["text/raw"],
        max_inputs: -1,
        max_outputs: -1,
      },
      {
        node_type: "engine/text",
        display_name: "Text Engine",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/plain", "text/html"],
        output_types: ["text/raw"],
        max_inputs: 1,
        max_outputs: -1,
      },
      {
        node_type: "engine/markitdown",
        display_name: "MarkItDown",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: ["application/pdf", "image/*", "text/plain", "text/html"],
        output_types: ["text/raw"],
        max_inputs: 1,
        max_outputs: 1,
        pipeline_restriction: "simple_only",
      },
      {
        node_type: "engine/docling",
        display_name: "Docling",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: ["application/pdf", "text/plain", "text/html", "image/*"],
        output_types: ["text/raw"],
        max_inputs: 1,
        max_outputs: 1,
      },
      {
        node_type: "output/markdown",
        display_name: "Markdown",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw", "text/plain"],
        output_types: ["text/markdown"],
        max_inputs: 1,
        max_outputs: 1,
      },
      {
        node_type: "output/plaintext",
        display_name: "Plain Text",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw", "text/plain"],
        output_types: ["text/plain+formatted"],
        max_inputs: 1,
        max_outputs: 1,
      },
      {
        node_type: "output/yaml",
        display_name: "YAML",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw", "text/plain"],
        output_types: ["application/yaml"],
        max_inputs: 1,
        max_outputs: 1,
      },
      {
        node_type: "end/final",
        display_name: "End",
        category: "end",
        config_schema: { type: "object", properties: {} },
        input_types: [
          "text/markdown",
          "text/plain+formatted",
          "application/yaml",
        ],
        output_types: [],
        max_inputs: -1,
        max_outputs: 0,
      },
    ],
    connection_rules: [],
  };
}

// ---------------------------------------------------------------------------
// Helper: build minimal WorkflowNode and ConnectionValidationInput
// ---------------------------------------------------------------------------

function makeNode(id: string, nodeType: string): WorkflowNode {
  return {
    id,
    type: nodeType,
    data: {
      label: nodeType,
      config: {},
      configSchema: { type: "object", properties: {} },
    },
  };
}

function buildMatrixInput(
  sourceType: string,
  targetType: string,
): ConnectionValidationInput {
  const sourceId = "source_node";
  const targetId = "target_node";
  return {
    sourceNodeId: sourceId,
    targetNodeId: targetId,
    nodes: [makeNode(sourceId, sourceType), makeNode(targetId, targetType)],
    edges: [],
    registry: buildFullRegistry(),
  };
}

/**
 * Determine the expected validity for a (source, target) pair.
 *
 * The frontend validateConnection checks:
 *   1. self-loop (not applicable here — different IDs)
 *   2. node existence in workflow nodes (always true — we add both)
 *   3. duplicate edge (not applicable — empty edges)
 *   4. max_inputs on target (rejected when >= 0 and currentInputs >= max)
 *   5. max_outputs on source (rejected when >= 0 and currentOutputs >= max)
 *   6. MIME type compatibility
 *
 * When metadata is undefined (unregistered type), all structural checks
 * are skipped and type compatibility defaults to true (empty arrays).
 * This means unregistered types pass validation in the frontend.
 */

// ---------------------------------------------------------------------------
// 120-cell connection matrix
// ---------------------------------------------------------------------------
// processor/block_selector is NOT in the registry. The frontend
// validateConnection resolves metadata=undefined for it, which causes
// all structural checks (max_inputs, max_outputs) to be skipped and
// isTypeCompatible to default to true (both arrays empty).
// Therefore, connections involving processor/block_selector are VALID
// in the frontend when the node is present in the nodes array.
//
// To keep the frontend matrix aligned with the backend expectations
// (where unregistered nodes = invalid), we test block_selector cells
// separately and document the behavioural divergence.
// ---------------------------------------------------------------------------

const CONNECTION_MATRIX: [string, string, boolean][] = [
  // --- Row 1: input/image (outputs: image/*) ---
  ["input/image", "processor/image_enhance", true],       // 1
  ["input/image", "processor/rotate", true],               // 2
  ["input/image", "processor/layout_detection", true],     // 3
  ["input/image", "engine/ocr", true],                     // 5
  ["input/image", "engine/model", true],                   // 6
  ["input/image", "engine/text", false],                   // 7
  ["input/image", "engine/markitdown", true],              // 8
  ["input/image", "engine/docling", true],                 // 9
  ["input/image", "output/markdown", false],               // 10
  ["input/image", "end/final", false],                     // 11
  // --- Row 2: input/pdf (outputs: application/pdf, image/*) ---
  ["input/pdf", "processor/image_enhance", true],          // 12
  ["input/pdf", "processor/rotate", true],                 // 13
  ["input/pdf", "processor/layout_detection", true],       // 14
  ["input/pdf", "engine/ocr", true],                       // 16
  ["input/pdf", "engine/model", true],                     // 17
  ["input/pdf", "engine/text", false],                     // 18
  ["input/pdf", "engine/markitdown", true],                // 19
  ["input/pdf", "engine/docling", true],                   // 20
  ["input/pdf", "output/markdown", false],                 // 21
  ["input/pdf", "end/final", false],                       // 22
  // --- Row 3: input/text (outputs: text/plain) ---
  ["input/text", "processor/image_enhance", false],        // 23
  ["input/text", "processor/rotate", false],               // 24
  ["input/text", "processor/layout_detection", false],     // 25
  ["input/text", "engine/ocr", false],                     // 27
  ["input/text", "engine/model", true],                    // 28
  ["input/text", "engine/text", true],                     // 29
  ["input/text", "engine/markitdown", true],               // 30
  ["input/text", "engine/docling", true],                  // 31
  ["input/text", "output/markdown", true],                 // 32
  ["input/text", "end/final", false],                      // 33
  // --- Row 4: processor/image_enhance (outputs: image/*) ---
  ["processor/image_enhance", "processor/image_enhance", true],    // 34
  ["processor/image_enhance", "processor/rotate", true],            // 35
  ["processor/image_enhance", "processor/layout_detection", true],  // 36
  ["processor/image_enhance", "engine/ocr", true],                  // 38
  ["processor/image_enhance", "engine/model", true],                // 39
  ["processor/image_enhance", "engine/text", false],                // 40
  ["processor/image_enhance", "engine/markitdown", true],           // 41
  ["processor/image_enhance", "engine/docling", true],              // 42
  ["processor/image_enhance", "output/markdown", false],            // 43
  ["processor/image_enhance", "end/final", false],                  // 44
  // --- Row 5: processor/rotate (outputs: image/*) ---
  ["processor/rotate", "processor/image_enhance", true],   // 45
  ["processor/rotate", "processor/rotate", true],           // 46
  ["processor/rotate", "processor/layout_detection", true], // 47
  ["processor/rotate", "engine/ocr", true],                 // 49
  ["processor/rotate", "engine/model", true],               // 50
  ["processor/rotate", "engine/text", false],               // 51
  ["processor/rotate", "engine/markitdown", true],          // 52
  ["processor/rotate", "engine/docling", true],             // 53
  ["processor/rotate", "output/markdown", false],           // 54
  ["processor/rotate", "end/final", false],                 // 55
  // --- Row 6: processor/layout_detection (outputs: application/x-layout-result) ---
  ["processor/layout_detection", "processor/image_enhance", false],    // 56
  ["processor/layout_detection", "processor/rotate", false],            // 57
  ["processor/layout_detection", "processor/layout_detection", false],  // 58
  ["processor/layout_detection", "engine/ocr", true],                   // 60
  ["processor/layout_detection", "engine/model", true],                 // 61
  ["processor/layout_detection", "engine/text", false],                 // 62
  ["processor/layout_detection", "engine/markitdown", false],           // 63
  ["processor/layout_detection", "engine/docling", false],              // 64
  ["processor/layout_detection", "output/markdown", false],             // 65
  ["processor/layout_detection", "end/final", false],                   // 66
  // --- Row 7: processor/block_selector — SKIPPED (not in registry) ---
  // See TestBlockSelectorFrontendBehaviour below for coverage.
  // --- Row 8: engine/ocr (outputs: text/raw) ---
  ["engine/ocr", "processor/image_enhance", false],    // 77
  ["engine/ocr", "processor/rotate", false],            // 78
  ["engine/ocr", "processor/layout_detection", false],  // 79
  ["engine/ocr", "engine/ocr", false],                  // 81
  ["engine/ocr", "engine/model", true],                 // 82
  ["engine/ocr", "engine/text", false],                 // 83
  ["engine/ocr", "engine/markitdown", false],           // 84
  ["engine/ocr", "engine/docling", false],              // 85
  ["engine/ocr", "output/markdown", true],              // 86
  ["engine/ocr", "end/final", false],                   // 87
  // --- Row 9: engine/model (outputs: text/raw) ---
  ["engine/model", "processor/image_enhance", false],  // 88
  ["engine/model", "processor/rotate", false],          // 89
  ["engine/model", "processor/layout_detection", false], // 90
  ["engine/model", "engine/ocr", false],                // 92
  ["engine/model", "engine/model", true],               // 93
  ["engine/model", "engine/text", false],               // 94
  ["engine/model", "engine/markitdown", false],         // 95
  ["engine/model", "engine/docling", false],            // 96
  ["engine/model", "output/markdown", true],            // 97
  ["engine/model", "end/final", false],                 // 98
  // --- Row 10: engine/text (outputs: text/raw) ---
  ["engine/text", "processor/image_enhance", false],   // 99
  ["engine/text", "processor/rotate", false],           // 100
  ["engine/text", "processor/layout_detection", false], // 101
  ["engine/text", "engine/ocr", false],                 // 103
  ["engine/text", "engine/model", true],                // 104
  ["engine/text", "engine/text", false],                // 105
  ["engine/text", "engine/markitdown", false],          // 106
  ["engine/text", "engine/docling", false],             // 107
  ["engine/text", "output/markdown", true],             // 108
  ["engine/text", "end/final", false],                  // 109
  // --- Row 11: engine/markitdown (outputs: text/raw) ---
  ["engine/markitdown", "processor/image_enhance", false],     // 110
  ["engine/markitdown", "processor/rotate", false],             // 111
  ["engine/markitdown", "processor/layout_detection", false],   // 112
  ["engine/markitdown", "engine/ocr", false],                   // 114
  ["engine/markitdown", "engine/model", true],                  // 115
  ["engine/markitdown", "engine/text", false],                  // 116
  ["engine/markitdown", "engine/markitdown", false],            // 117
  ["engine/markitdown", "engine/docling", false],               // 118
  ["engine/markitdown", "output/markdown", true],               // 119
  ["engine/markitdown", "end/final", false],                    // 120
  // --- Row 12: engine/docling (outputs: text/raw) ---
  ["engine/docling", "processor/image_enhance", false],   // 121
  ["engine/docling", "processor/rotate", false],            // 122
  ["engine/docling", "processor/layout_detection", false],  // 123
  ["engine/docling", "engine/ocr", false],                  // 125
  ["engine/docling", "engine/model", true],                 // 126
  ["engine/docling", "engine/text", false],                 // 127
  ["engine/docling", "engine/markitdown", false],           // 128
  ["engine/docling", "engine/docling", false],              // 129
  ["engine/docling", "output/markdown", true],              // 130
  ["engine/docling", "end/final", false],                   // 131
  // --- Row 13: output/markdown (outputs: text/markdown) ---
  ["output/markdown", "processor/image_enhance", false],  // 132
  ["output/markdown", "processor/rotate", false],          // 133
  ["output/markdown", "processor/layout_detection", false], // 134
  ["output/markdown", "engine/ocr", false],                // 136
  ["output/markdown", "engine/model", false],              // 137
  ["output/markdown", "engine/text", false],               // 138
  ["output/markdown", "engine/markitdown", false],         // 139
  ["output/markdown", "engine/docling", false],            // 140
  ["output/markdown", "output/markdown", false],           // 141
  ["output/markdown", "end/final", true],                  // 142
];

// ---------------------------------------------------------------------------
// processor/block_selector cells (unregistered node type)
// ---------------------------------------------------------------------------
// When a node type is not in the registry, the frontend resolveNode returns
// { node, metadata: undefined }. With undefined metadata:
//   - max_inputs/max_outputs checks are skipped
//   - isTypeCompatible defaults to true (empty arrays)
// So the frontend considers these connections VALID — unlike the backend
// which returns False when a node definition is missing.
// ---------------------------------------------------------------------------

const BLOCK_SELECTOR_CELLS: [string, string][] = [
  // As target (cells 4, 15, 26, 37, 48, 59)
  ["input/image", "processor/block_selector"],
  ["input/pdf", "processor/block_selector"],
  ["input/text", "processor/block_selector"],
  ["processor/image_enhance", "processor/block_selector"],
  ["processor/rotate", "processor/block_selector"],
  ["processor/layout_detection", "processor/block_selector"],
  // As source (cells 67-78)
  ["processor/block_selector", "processor/image_enhance"],
  ["processor/block_selector", "processor/rotate"],
  ["processor/block_selector", "processor/layout_detection"],
  ["processor/block_selector", "processor/block_selector"],
  ["processor/block_selector", "engine/ocr"],
  ["processor/block_selector", "engine/model"],
  ["processor/block_selector", "engine/text"],
  ["processor/block_selector", "engine/markitdown"],
  ["processor/block_selector", "engine/docling"],
  ["processor/block_selector", "output/markdown"],
  ["processor/block_selector", "end/final"],
  // As target from engines/output (cells 80, 91, 102, 113, 124, 135)
  ["engine/ocr", "processor/block_selector"],
  ["engine/model", "processor/block_selector"],
  ["engine/text", "processor/block_selector"],
  ["engine/markitdown", "processor/block_selector"],
  ["engine/docling", "processor/block_selector"],
  ["output/markdown", "processor/block_selector"],
];

describe("Connection Matrix (143-cell exhaustive)", () => {
  it.each(CONNECTION_MATRIX)(
    "%s -> %s should be %s",
    (sourceType, targetType, expected) => {
      const input = buildMatrixInput(sourceType, targetType);
      const result = validateConnection(input);
      expect(result.isValid).toBe(expected);
    },
  );

  it("matrix covers 120 registered-type cells (143 - 23 block_selector)", () => {
    expect(CONNECTION_MATRIX.length).toBe(120);
    expect(CONNECTION_MATRIX.length + BLOCK_SELECTOR_CELLS.length).toBe(143);
  });
});

describe("Block selector cells (unregistered node — frontend allows)", () => {
  it.each(BLOCK_SELECTOR_CELLS)(
    "%s -> %s passes frontend validation (metadata undefined)",
    (sourceType, targetType) => {
      const input = buildMatrixInput(sourceType, targetType);
      const result = validateConnection(input);
      // Frontend allows connections when registry metadata is missing
      // because all constraint checks are skipped.
      expect(result.isValid).toBe(true);
      expect(result.isTypeCompatible).toBe(true);
    },
  );
});

describe("Structural constraints in validateConnection", () => {
  it("rejects self-loop", () => {
    const input: ConnectionValidationInput = {
      sourceNodeId: "node_a",
      targetNodeId: "node_a",
      nodes: [makeNode("node_a", "engine/ocr")],
      edges: [],
      registry: buildFullRegistry(),
    };
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("self_loop");
  });

  it("rejects duplicate edge", () => {
    const input: ConnectionValidationInput = {
      sourceNodeId: "src",
      targetNodeId: "tgt",
      nodes: [makeNode("src", "input/pdf"), makeNode("tgt", "engine/ocr")],
      edges: [{ id: "e1", source: "src", target: "tgt" }],
      registry: buildFullRegistry(),
    };
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("duplicate_edge");
  });

  it("rejects connection to input node (max_inputs=0)", () => {
    const input = buildMatrixInput("engine/ocr", "input/image");
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("max_inputs");
  });

  it("rejects connection from end/final (max_outputs=0)", () => {
    const input = buildMatrixInput("end/final", "engine/ocr");
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("max_outputs");
  });

  it("rejects max_inputs exceeded when edge exists", () => {
    const input: ConnectionValidationInput = {
      sourceNodeId: "src2",
      targetNodeId: "tgt",
      nodes: [
        makeNode("src1", "input/pdf"),
        makeNode("src2", "input/image"),
        makeNode("tgt", "processor/image_enhance"),
      ],
      edges: [{ id: "e1", source: "src1", target: "tgt" }],
      registry: buildFullRegistry(),
    };
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("max_inputs");
  });

  it("rejects max_outputs exceeded on markitdown (max_outputs=1)", () => {
    const input: ConnectionValidationInput = {
      sourceNodeId: "mk",
      targetNodeId: "model2",
      nodes: [
        makeNode("mk", "engine/markitdown"),
        makeNode("model1", "engine/model"),
        makeNode("model2", "engine/model"),
      ],
      edges: [{ id: "e1", source: "mk", target: "model1" }],
      registry: buildFullRegistry(),
    };
    const result = validateConnection(input);
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("max_outputs");
  });
});
