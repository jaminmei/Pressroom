import { describe, expect, it } from "vitest";

import { validateWorkflowDefinition } from "@/features/workflow-editor/utils/workflowValidator";
import type { NodeRegistryNode } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

const requiredFileSchema = {
  type: "object" as const,
  properties: {
    file: { type: "file" as const }
  },
  required: ["file"]
};

function buildNodes(): WorkflowNode[] {
  return [
    {
      id: "input_1",
      type: "input/pdf",
      data: {
        label: "Input",
        config: {},
        configSchema: requiredFileSchema
      }
    },
    {
      id: "engine_1",
      type: "engine/ocr",
      data: {
        label: "Engine",
        config: { model: "paddleocr" },
        configSchema: {
          type: "object",
          properties: {
            model: { type: "string" }
          },
          required: ["model"]
        }
      }
    },
    {
      id: "output_1",
      type: "output/markdown",
      data: {
        label: "Output",
        config: {},
        configSchema: { type: "object", properties: {} }
      }
    },
    {
      id: "end_1",
      type: "end/final",
      data: {
        label: "End",
        config: {},
        configSchema: { type: "object", properties: {} }
      }
    }
  ];
}

function buildEdges(): WorkflowEdge[] {
  return [
    { id: "e1", source: "input_1", target: "engine_1" },
    { id: "e2", source: "engine_1", target: "output_1" },
    { id: "e3", source: "output_1", target: "end_1" }
  ];
}

function buildRegistryNodes(): NodeRegistryNode[] {
  return [
    {
      node_type: "input/pdf",
      display_name: "Input",
      category: "input",
      config_schema: requiredFileSchema,
      output_types: ["application/pdf"],
      max_inputs: 0,
      max_outputs: -1
    },
    {
      node_type: "engine/ocr",
      display_name: "OCR",
      category: "engine",
      config_schema: {
        type: "object",
        properties: {
          model: { type: "string" }
        },
        required: ["model"]
      },
      input_types: ["application/pdf"],
      output_types: ["text/raw"],
      max_inputs: 1,
      max_outputs: 1
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
      config_schema: {
        type: "object",
        properties: {
          code: { type: "string" },
          input_mode: { type: "string", enum: ["all_upstream", "custom_bindings"] },
          input_bindings: {
            type: "array",
            items: {
              type: "object",
              properties: {
                name: { type: "string", minLength: 1 },
                selector: {
                  type: "array",
                  items: { type: "string" },
                  minItems: 2
                }
              },
              required: ["name", "selector"]
            }
          }
        },
        required: ["code"]
      },
      input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: -1 }],
      output_types: ["application/x-adaptor-output"],
      max_inputs: -1,
      max_outputs: -1
    },
    {
      node_type: "processor/iteration",
      display_name: "Iteration",
      category: "processor",
      config_schema: {
        type: "object",
        properties: {
          engine_node_type: { type: "string" },
          engine_config: { type: "object", properties: {} },
          iterate_over: { type: "string" },
          item_input_port: { type: "string" },
          mode: { type: "string" },
          max_concurrency: { type: "integer", minimum: 1, maximum: 10 },
          error_handling: { type: "string" }
        },
        required: [
          "engine_node_type",
          "engine_config",
          "iterate_over",
          "item_input_port",
          "mode",
          "max_concurrency",
          "error_handling"
        ]
      },
      input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: 1 }],
      output_types: ["application/x-iteration-output"],
      max_inputs: 1,
      max_outputs: -1
    }
  ];
}

describe("validateWorkflowDefinition", () => {
  it("returns blocking error when input node is missing", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes().filter((node) => !node.type.startsWith("input/")),
      edges: [{ id: "e1", source: "engine_1", target: "output_1" }],
      nodeConfigs: { engine_1: { model: "paddleocr" }, output_1: {} },
      uploadedFiles: {},
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "WORKFLOW_NO_INPUT")).toBe(true);
  });

  it("returns executable true when no legacy output nodes exist", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes().filter((node) => !node.type.startsWith("output/")),
      edges: [
        { id: "e1", source: "input_1", target: "engine_1" },
        { id: "e2", source: "engine_1", target: "end_1" }
      ],
      nodeConfigs: { input_1: { file: "$file_0" }, engine_1: { model: "paddleocr", provider_id: "provider-1" }, end_1: {} },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(true);
  });

  it("returns blocking error when input file is missing", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges(),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: {},
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "MISSING_REQUIRED_CONFIG")).toBe(
      true
    );
  });

  it("returns blocking error when required config field is missing", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges(),
      nodeConfigs: { input_1: { file: "$file_0" }, engine_1: {}, output_1: {}, end_1: {} },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "MISSING_REQUIRED_CONFIG")).toBe(
      true
    );
  });

  it("returns warning when workflow has an isolated node", () => {
    const nodes = [...buildNodes()];
    nodes.push({
      id: "engine_2",
      type: "engine/ocr",
      data: {
        label: "孤立節點",
        config: { model: "paddleocr" },
        configSchema: { type: "object", properties: {} }
      }
    });
    const result = validateWorkflowDefinition({
      nodes,
      edges: buildEdges(),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {},
        engine_2: { model: "paddleocr" }
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(
      result.warnings.some(
        (error) => error.code === "WORKFLOW_ORPHAN_NODE" && error.nodeId === "engine_2"
      )
    ).toBe(true);
  });

  it("returns blocking error when workflow contains cycle", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: [
        { id: "e1", source: "input_1", target: "engine_1" },
        { id: "e2", source: "engine_1", target: "output_1" },
        { id: "e3", source: "output_1", target: "input_1" }
      ],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "WORKFLOW_CYCLE")).toBe(true);
  });

  it("does not classify a fully connected OCR workflow as orphaned", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges(),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr", provider_id: "provider-1" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.warnings.some((warning) => warning.code === "WORKFLOW_ORPHAN_NODE")).toBe(false);
  });

  it("returns warning when workflow uses unavailable engine", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges(),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr", provider_id: "provider-1" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      unavailableEngines: ["ocr"],
      registryNodes: buildRegistryNodes()
    });

    expect(result.warnings.some((warning) => warning.code === "ENGINE_UNAVAILABLE")).toBe(true);
  });

  it("returns blocking error when connection violates category rules", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: [{ id: "e1", source: "output_1", target: "engine_1" }],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      connectionRules: [
        { from_category: "input", to_categories: ["engine"] },
        { from_category: "engine", to_categories: ["output"] }
      ],
      registryNodes: buildRegistryNodes()
    });

    expect(result.blockingErrors.some((error) => error.code === "INVALID_CONNECTION")).toBe(true);
  });

  it("returns executable true when there is only warning", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges(),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr", provider_id: "provider-1" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      unavailableEngines: ["ocr"],
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(true);
    expect(result.blockingErrors).toHaveLength(0);
    expect(result.warnings.length).toBeGreaterThan(0);
  });

  it("returns blocking error when end node is missing", () => {
    const nodes = buildNodes().filter((node) => node.type !== "end/final");
    const edges = buildEdges().filter((edge) => edge.target !== "end_1" && edge.source !== "end_1");

    const result = validateWorkflowDefinition({
      nodes,
      edges,
      nodeConfigs: { input_1: { file: "$file_0" }, engine_1: { model: "paddleocr" }, output_1: {} },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "WORKFLOW_NO_END")).toBe(true);
  });

  it("returns blocking error when multiple end nodes exist", () => {
    const result = validateWorkflowDefinition({
      nodes: [
        ...buildNodes(),
        {
          id: "end_2",
          type: "end/final",
          data: {
            label: "End 2",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        }
      ],
      edges: [...buildEdges(), { id: "e4", source: "output_1", target: "end_2" }],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {},
        end_2: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "WORKFLOW_MULTIPLE_END")).toBe(
      true
    );
  });

  it("returns blocking error when the end node has downstream edges", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: [...buildEdges(), { id: "e4", source: "end_1", target: "engine_1" }],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(result.blockingErrors.some((error) => error.code === "END_NODE_NOT_TERMINAL")).toBe(
      true
    );
  });

  it("does not require provider_id for adaptor and iteration nodes", () => {
    const result = validateWorkflowDefinition({
      nodes: [
        {
          id: "input_1",
          type: "input/text",
          data: { label: "Text", config: {}, configSchema: requiredFileSchema }
        },
        {
          id: "adaptor_1",
          type: "processor/adaptor",
          data: {
            label: "Adaptor",
            config: {},
            configSchema: buildRegistryNodes().find((node) => node.node_type === "processor/adaptor")!.config_schema
          }
        },
        {
          id: "iteration_1",
          type: "processor/iteration",
          data: {
            label: "Iteration",
            config: {},
            configSchema: buildRegistryNodes().find((node) => node.node_type === "processor/iteration")!.config_schema
          }
        },
        {
          id: "end_1",
          type: "end/final",
          data: { label: "End", config: {}, configSchema: { type: "object", properties: {} } }
        }
      ],
      edges: [
        { id: "e1", source: "input_1", target: "adaptor_1" },
        { id: "e2", source: "adaptor_1", target: "iteration_1" },
        { id: "e3", source: "iteration_1", target: "end_1" }
      ],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        adaptor_1: { code: "def main(inputs): return {'text': 'ok'}" },
        iteration_1: {
          engine_node_type: "engine/ocr",
          engine_config: {},
          iterate_over: "binary",
          item_input_port: "images",
          mode: "sequential",
          max_concurrency: 1,
          error_handling: "terminate"
        },
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["text"], "doc.txt", { type: "text/plain" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.blockingErrors.some((error) => error.code === "MISSING_PROVIDER")).toBe(false);
  });

  it("accepts wildcard adaptor and iteration connections", () => {
    const result = validateWorkflowDefinition({
      nodes: [
        {
          id: "input_1",
          type: "input/text",
          data: { label: "Text", config: {}, configSchema: requiredFileSchema }
        },
        {
          id: "adaptor_1",
          type: "processor/adaptor",
          data: {
            label: "Adaptor",
            config: {},
            configSchema: buildRegistryNodes().find((node) => node.node_type === "processor/adaptor")!.config_schema
          }
        },
        {
          id: "iteration_1",
          type: "processor/iteration",
          data: {
            label: "Iteration",
            config: {},
            configSchema: buildRegistryNodes().find((node) => node.node_type === "processor/iteration")!.config_schema
          }
        },
        {
          id: "end_1",
          type: "end/final",
          data: { label: "End", config: {}, configSchema: { type: "object", properties: {} } }
        }
      ],
      edges: [
        { id: "e1", source: "input_1", target: "adaptor_1" },
        { id: "e2", source: "adaptor_1", target: "iteration_1" },
        { id: "e3", source: "iteration_1", target: "end_1" }
      ],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        adaptor_1: { code: "def main(inputs): return {'binary': b'x'}" },
        iteration_1: {
          engine_node_type: "engine/ocr",
          engine_config: {},
          iterate_over: "binary",
          item_input_port: "images",
          mode: "sequential",
          max_concurrency: 1,
          error_handling: "terminate"
        },
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["text"], "doc.txt", { type: "text/plain" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.blockingErrors.some((error) => error.code === "TYPE_INCOMPATIBLE")).toBe(false);
    expect(result.isExecutable).toBe(true);
  });

  it("returns warning when end node has no upstream connection", () => {
    const result = validateWorkflowDefinition({
      nodes: buildNodes(),
      edges: buildEdges().filter((edge) => edge.target !== "end_1"),
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      registryNodes: buildRegistryNodes()
    });

    expect(result.warnings.some((warning) => warning.code === "WORKFLOW_ORPHAN_NODE")).toBe(true);
  });

  it("returns blocking error when connection exceeds max_inputs", () => {
    const result = validateWorkflowDefinition({
      nodes: [
        ...buildNodes(),
        {
          id: "input_2",
          type: "input/pdf",
          data: {
            label: "Input 2",
            config: {},
            configSchema: requiredFileSchema
          }
        }
      ],
      edges: [...buildEdges(), { id: "e4", source: "input_2", target: "engine_1" }],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        input_2: { file: "$file_1" },
        engine_1: { model: "paddleocr" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: {
        input_1: new File(["pdf"], "doc1.pdf", { type: "application/pdf" }),
        input_2: new File(["pdf"], "doc2.pdf", { type: "application/pdf" })
      },
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(
      result.blockingErrors.some(
        (error) => error.code === "INVALID_CONNECTION" && error.nodeId === "engine_1"
      )
    ).toBe(true);
  });

  it("returns blocking error when mime types are incompatible", () => {
    const result = validateWorkflowDefinition({
      nodes: [
        buildNodes()[0],
        buildNodes()[1],
        {
          id: "output_2",
          type: "output/yaml",
          data: {
            label: "YAML",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        },
        buildNodes()[3]
      ],
      edges: [
        { id: "e1", source: "input_1", target: "engine_1" },
        { id: "e2", source: "engine_1", target: "output_2" },
        { id: "e3", source: "output_2", target: "end_1" }
      ],
      nodeConfigs: {
        input_1: { file: "$file_0" },
        engine_1: { model: "paddleocr" },
        output_2: {},
        end_1: {}
      },
      uploadedFiles: { input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" }) },
      connectionRules: [
        { from_category: "input", to_categories: ["engine"] },
        { from_category: "engine", to_categories: ["output"] },
        { from_category: "output", to_categories: ["end"] }
      ],
      registryNodes: buildRegistryNodes()
    });

    expect(result.isExecutable).toBe(false);
    expect(
      result.blockingErrors.some(
        (error) => error.code === "TYPE_INCOMPATIBLE" && error.nodeId === "output_2"
      )
    ).toBe(true);
  });
});
