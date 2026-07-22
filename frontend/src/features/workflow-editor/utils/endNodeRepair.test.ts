import { describe, expect, it } from "vitest";

import {
  ensureSingleEndNodeGraph,
  resolvePreferredEditableNodeId
} from "@/features/workflow-editor/utils/endNodeRepair";
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
      node_type: "output/plaintext",
      display_name: "Plain Text Output",
      category: "output",
      config_schema: { type: "object", properties: {} },
      input_types: ["text/raw"],
      output_types: ["text/plain"]
    },
    {
      node_type: "end/final",
      display_name: "Workflow End",
      category: "end",
      config_schema: { type: "object", properties: {} },
      input_types: ["text/plain"],
      output_types: []
    }
  ],
  connection_rules: [
    { from_category: "input", to_categories: ["engine"] },
    { from_category: "engine", to_categories: ["output"] },
    { from_category: "output", to_categories: ["end"] }
  ]
};

function buildLegacyNodes(): WorkflowNode[] {
  return [
    {
      id: "input_1",
      type: "input/pdf",
      data: {
        label: "Input",
        config: {},
        configSchema: { type: "object", properties: {} }
      },
      position: { x: 100, y: 160 }
    },
    {
      id: "engine_1",
      type: "engine/ocr",
      data: {
        label: "OCR",
        config: {},
        configSchema: { type: "object", properties: {} }
      },
      position: { x: 380, y: 160 }
    },
    {
      id: "output_1",
      type: "output/text",
      data: {
        label: "Legacy Output",
        config: {},
        configSchema: { type: "object", properties: {} }
      },
      position: { x: 660, y: 160 }
    }
  ];
}

function buildLegacyEdges(): WorkflowEdge[] {
  return [
    { id: "e1", source: "input_1", target: "engine_1" },
    { id: "e2", source: "engine_1", target: "output_1" }
  ];
}

describe("ensureSingleEndNodeGraph", () => {
  it("removes a legacy output node without injecting an end node", () => {
    const repairedGraph = ensureSingleEndNodeGraph({
      nodes: buildLegacyNodes(),
      edges: buildLegacyEdges(),
      registry
    });

    expect(repairedGraph.nodes.find((node) => node.id === "output_1")).toBeUndefined();
    expect(repairedGraph.nodes.filter((node) => node.type === "end/final")).toHaveLength(0);
    expect(repairedGraph.edges).toEqual([{ id: "e1", source: "input_1", target: "engine_1" }]);
  });

  it("preserves multiple existing end nodes for validator-driven rejection", () => {
    const repairedGraph = ensureSingleEndNodeGraph({
      nodes: [
        ...buildLegacyNodes().map((node) =>
          node.id === "output_1" ? { ...node, type: "output/plaintext" } : node
        ),
        {
          id: "end_1",
          type: "end/final",
          data: {
            label: "End 1",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        },
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
      edges: [...buildLegacyEdges(), { id: "e3", source: "output_1", target: "end_1" }],
      registry
    });

    expect(repairedGraph.nodes.filter((node) => node.type === "end/final").map((node) => node.id)).toEqual([
      "end_1",
      "end_2"
    ]);
  });

  it("keeps blank canvases without outputs free of injected end nodes", () => {
    const repairedGraph = ensureSingleEndNodeGraph({
      nodes: [],
      edges: [],
      registry
    });

    expect(repairedGraph.nodes).toEqual([]);
    expect(repairedGraph.edges).toEqual([]);
  });
});

describe("resolvePreferredEditableNodeId", () => {
  it("prefers input nodes over injected end nodes", () => {
    expect(
      resolvePreferredEditableNodeId([
        ...buildLegacyNodes(),
        {
          id: "end_1",
          type: "end/final",
          data: {
            label: "End",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        }
      ])
    ).toBe("input_1");
  });
});
