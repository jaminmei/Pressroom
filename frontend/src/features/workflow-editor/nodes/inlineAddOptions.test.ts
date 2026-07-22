import { describe, expect, it } from "vitest";

import { resolveInlineAddNodeOptions } from "@/features/workflow-editor/nodes/inlineAddOptions";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

const registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
  nodes: [
    {
      node_type: "input/pdf",
      display_name: "PDF Input",
      category: "input",
      config_schema: { type: "object", properties: {} },
      output_types: ["application/pdf"]
    },
    {
      node_type: "engine/ocr",
      display_name: "OCR Engine",
      category: "engine",
      config_schema: { type: "object", properties: {} },
      input_types: ["application/pdf"],
      output_types: ["text/raw"]
    },
    {
      node_type: "engine/model",
      display_name: "Model Engine",
      category: "engine",
      config_schema: { type: "object", properties: {} },
      input_types: ["application/pdf"],
      output_types: ["text/raw"]
    },
    {
      node_type: "output/markdown",
      display_name: "Markdown Output",
      category: "output",
      config_schema: { type: "object", properties: {} },
      input_types: ["text/raw"],
      output_types: ["text/markdown"]
    }
  ],
  connection_rules: [
    { from_category: "input", to_categories: ["engine", "output"] },
    { from_category: "engine", to_categories: ["engine", "output"] },
    { from_category: "output", to_categories: [] }
  ]
};

const nodes: WorkflowNode[] = [
  {
    id: "input_1",
    type: "input/pdf",
    data: {
      label: "PDF Input",
      config: {},
      configSchema: { type: "object", properties: {} },
      outputTypes: ["application/pdf"]
    },
    position: { x: 0, y: 0 }
  },
  {
    id: "output_1",
    type: "output/markdown",
    data: {
      label: "Markdown Output",
      config: {},
      configSchema: { type: "object", properties: {} },
      inputTypes: ["text/raw"],
      outputTypes: ["text/markdown"]
    },
    position: { x: 320, y: 0 }
  }
];

const edges: WorkflowEdge[] = [{ id: "edge-main", source: "input_1", target: "output_1" }];

describe("resolveInlineAddNodeOptions", () => {
  it("returns only nodes that can be inserted between the current source and target", () => {
    const options = resolveInlineAddNodeOptions({
      edgeId: "edge-main",
      sourceNodeId: "input_1",
      targetNodeId: "output_1",
      nodes,
      edges,
      registry
    });

    expect(options.map((node) => node.node_type)).toEqual(["engine/model", "engine/ocr"]);
  });
});
