import { describe, expect, it } from "vitest";

import { buildValidatedEdge, getConnectionFailureMessage } from "@/features/workflow-editor/components/canvasConnection";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";

function buildRegistry(): Pick<NodeRegistryResponse, "nodes" | "connection_rules"> {
  return {
    nodes: [
      {
        node_type: "input/pdf",
        display_name: "PDF",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["application/pdf"],
        max_inputs: 0,
        max_outputs: -1
      },
      {
        node_type: "engine/ocr",
        display_name: "OCR",
        category: "engine",
        config_schema: { type: "object", properties: {} },
        input_types: ["application/pdf"],
        output_types: ["text/raw"],
        max_inputs: 1,
        max_outputs: -1
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
      }
    ],
    connection_rules: [
      { from_category: "input", to_categories: ["processor", "engine", "output"] },
      { from_category: "processor", to_categories: ["processor", "engine"] },
      { from_category: "engine", to_categories: ["output"] },
      { from_category: "output", to_categories: [] }
    ]
  };
}

const nodes: WorkflowNode[] = [
  {
    id: "input_1",
    type: "input/pdf",
    data: {
      label: "PDF",
      config: {},
      configSchema: { type: "object", properties: {} }
    }
  },
  {
    id: "engine_1",
    type: "engine/ocr",
    data: {
      label: "OCR",
      config: {},
      configSchema: { type: "object", properties: {} }
    }
  },
  {
    id: "output_1",
    type: "output/yaml",
    data: {
      label: "YAML",
      config: {},
      configSchema: { type: "object", properties: {} }
    }
  }
];

describe("buildValidatedEdge", () => {
  it("returns null for invalid connection", () => {
    const result = buildValidatedEdge({
      connection: { source: "output_1", target: "input_1" },
      nodes,
      edges: [],
      registry: buildRegistry()
    });

    expect(result.edge).toBeNull();
    expect(result.errorReason).toBe("max_inputs");
  });

  it("rejects type mismatch edge", () => {
    const result = buildValidatedEdge({
      connection: { source: "engine_1", target: "output_1" },
      nodes,
      edges: [],
      registry: buildRegistry()
    });

    expect(result.edge).toBeNull();
    expect(result.errorReason).toBe("type_incompatible");
  });

  it("creates normal edge for compatible connection", () => {
    const result = buildValidatedEdge({
      connection: { source: "input_1", target: "engine_1" },
      nodes,
      edges: [],
      registry: buildRegistry()
    });

    expect(result.edge).not.toBeNull();
    expect(result.edge?.data?.isTypeWarning).toBe(false);
    expect(result.edge?.style?.stroke).toBe("#7132f5");
  });
});

describe("getConnectionFailureMessage", () => {
  it("returns Chinese message for each known reason", () => {
    expect(getConnectionFailureMessage("self_loop")).toBe("不能連接到自身節點");
    expect(getConnectionFailureMessage("duplicate_edge")).toBe("這兩個節點之間已存在連線");
    expect(getConnectionFailureMessage("type_incompatible")).toBe("輸出類型與輸入類型不相容");
    expect(getConnectionFailureMessage("max_inputs")).toBe("目標節點已達到最大輸入連線數");
    expect(getConnectionFailureMessage("max_outputs")).toBe("來源節點已達到最大輸出連線數");
    expect(getConnectionFailureMessage("unknown_node")).toBe("找不到對應的節點");
  });

  it("returns fallback for unexpected reason", () => {
    const result = getConnectionFailureMessage("something_new" as never);
    expect(result).toContain("連線失敗");
    expect(result).toContain("something_new");
  });
});
