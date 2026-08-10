import { describe, expect, it } from "vitest";

import {
  type ConnectionValidationInput,
  type ConnectionValidationReason,
  validateConnection
} from "@/features/workflow-editor/utils/connectionValidator";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

function buildRegistry(): Pick<NodeRegistryResponse, "nodes" | "connection_rules"> {
  return {
    nodes: [
      {
        node_type: "input/pdf",
        display_name: "PDF 輸入",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["application/pdf"],
        max_inputs: 0,
        max_outputs: -1
      },
      {
        node_type: "input/image",
        display_name: "圖片輸入",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["image/*"],
        max_inputs: 0,
        max_outputs: -1
      },
      {
        node_type: "engine/ocr",
        display_name: "OCR",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: ["application/pdf", "image/*"],
        output_types: ["text/raw"],
        max_inputs: 1,
        max_outputs: -1
      },
      {
        node_type: "output/markdown",
        display_name: "Markdown",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw"],
        output_types: [],
        max_inputs: 1,
        max_outputs: 1
      },
      {
        node_type: "output/yaml",
        display_name: "YAML",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["layout/annotated"],
        output_types: [],
        max_inputs: 1,
        max_outputs: 0
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
          "application/x-layout-result"
        ],
        output_types: ["text/raw"],
        max_inputs: -1,
        max_outputs: -1
      },
      {
        node_type: "input/text",
        display_name: "Text 輸入",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["text/plain"],
        max_inputs: 0,
        max_outputs: -1
      },
      {
        node_type: "output/plaintext",
        display_name: "Plain Text",
        category: "output",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw", "text/plain"],
        output_types: ["text/plain+formatted"],
        max_inputs: 1,
        max_outputs: 1
      },
      {
        node_type: "end/final",
        display_name: "End",
        category: "end",
        config_schema: { type: "object", properties: {} },
        input_types: [
          "text/raw",
          "text/plain",
          "text/markdown",
          "image/*",
          "application/x-iteration-output"
        ],
        input_ports: [{
          name: "input",
          accepted_types: [
            "text/raw",
            "text/plain",
            "text/markdown",
            "image/*",
            "application/x-iteration-output"
          ],
          required: true,
          max_connections: -1
        }],
        output_types: [],
        max_inputs: -1,
        max_outputs: 0
      },
      {
        node_type: "processor/adaptor",
        display_name: "Adaptor",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: -1 }],
        output_types: ["application/x-adaptor-output"],
        max_inputs: -1,
        max_outputs: -1
      },
      {
        node_type: "processor/iteration",
        display_name: "Iteration",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: 1 }],
        output_types: ["application/x-iteration-output"],
        max_inputs: 1,
        max_outputs: -1
      }
    ],
    connection_rules: []
  };
}

function buildNodes(): WorkflowNode[] {
  return [
    {
      id: "input_1",
      type: "input/pdf",
      data: { label: "PDF", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "engine_1",
      type: "engine/ocr",
      data: { label: "OCR", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "input_2",
      type: "input/image",
      data: { label: "Image", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "output_1",
      type: "output/markdown",
      data: { label: "MD", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "output_2",
      type: "output/yaml",
      data: { label: "YAML", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "engine_model",
      type: "engine/model",
      data: { label: "Model", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "input_text",
      type: "input/text",
      data: { label: "Text", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "output_pt",
      type: "output/plaintext",
      data: { label: "PT", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "end_1",
      type: "end/final",
      data: { label: "End", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "adaptor_1",
      type: "processor/adaptor",
      data: { label: "Adaptor", config: {}, configSchema: { type: "object", properties: {} } }
    },
    {
      id: "iteration_1",
      type: "processor/iteration",
      data: { label: "Iteration", config: {}, configSchema: { type: "object", properties: {} } }
    }
  ];
}

function buildInput(overrides: Partial<ConnectionValidationInput> = {}): ConnectionValidationInput {
  return {
    sourceNodeId: "input_1",
    targetNodeId: "engine_1",
    nodes: buildNodes(),
    edges: [],
    registry: buildRegistry(),
    ...overrides
  };
}

function expectInvalidReason(
  result: ReturnType<typeof validateConnection>,
  reason: ConnectionValidationReason
) {
  expect(result.isValid).toBe(false);
  expect(result.reason).toBe(reason);
}

describe("validateConnection", () => {
  it("accepts valid connection input -> engine", () => {
    const result = validateConnection(buildInput());

    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });

  it("allows engine-to-engine connection when type compatible", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "engine_1", targetNodeId: "engine_model" })
    );
    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });

  it("allows model-to-model chaining", () => {
    const nodes: WorkflowNode[] = [
      ...buildNodes(),
      {
        id: "engine_model_2",
        type: "engine/model",
        data: { label: "Model 2", config: {}, configSchema: { type: "object" as const, properties: {} } }
      }
    ];
    const result = validateConnection(
      buildInput({ sourceNodeId: "engine_model", targetNodeId: "engine_model_2", nodes })
    );
    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });

  it("allows input/text to output/plaintext (text/plain matches)", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "input_text", targetNodeId: "output_pt" })
    );
    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });

  it("rejects end node as source (empty output_types)", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "end_1", targetNodeId: "engine_1" })
    );
    expect(result.isValid).toBe(false);
    expect(result.reason).toBe("max_outputs");
  });

  it("allows cross-category type-compatible connections without category_rule", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "output_1", targetNodeId: "input_1" })
    );
    expect(result.isValid).toBe(false);
    // Should be max_outputs or max_inputs, NOT category_rule
    expect(result.reason).not.toBe("category_rule");
  });

  it("rejects when target reaches max_inputs", () => {
    const existingEdges: WorkflowEdge[] = [{ id: "e1", source: "input_1", target: "engine_1" }];

    const result = validateConnection(
      buildInput({
        sourceNodeId: "input_2",
        targetNodeId: "engine_1",
        edges: existingEdges
      })
    );

    expectInvalidReason(result, "max_inputs");
  });

  it("rejects when mime type is not compatible", () => {
    const result = validateConnection(
      buildInput({
        sourceNodeId: "engine_1",
        targetNodeId: "output_2"
      })
    );

    expect(result.isValid).toBe(false);
    expect(result.isTypeCompatible).toBe(false);
    expect(result.reason).toBe("type_incompatible");
  });

  it("rejects duplicate edge", () => {
    const result = validateConnection(
      buildInput({
        edges: [{ id: "e1", source: "input_1", target: "engine_1" }]
      })
    );

    expectInvalidReason(result, "duplicate_edge");
  });

  it("treats universal mime target as compatible", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "input_text", targetNodeId: "adaptor_1" })
    );

    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });

  it("treats universal mime source as compatible with iteration input", () => {
    const result = validateConnection(
      buildInput({ sourceNodeId: "adaptor_1", targetNodeId: "iteration_1" })
    );

    expect(result).toEqual({ isValid: true, isTypeCompatible: true });
  });
});
