import { describe, expect, it } from "vitest";

import {
  buildEndpointConnection,
  resolveCompatibleNodeOptions,
  resolveEndpointNodePosition
} from "@/features/workflow-editor/nodes/endpointAddOptions";
import type { NodeRegistryResponse } from "@/types/node-registry";

function buildRegistry(): Pick<NodeRegistryResponse, "nodes" | "connection_rules"> {
  return {
    nodes: [
      {
        node_type: "input/pdf",
        display_name: "PDF Input",
        category: "input",
        config_schema: { type: "object", properties: {} },
        output_types: ["application/pdf"]
      },
      {
        node_type: "processor/layout_detection",
        display_name: "Layout Detection",
        category: "processor",
        config_schema: { type: "object", properties: {} },
        input_types: ["application/pdf"],
        output_types: ["layout/annotated"]
      },
      {
        node_type: "engine/ocr",
        display_name: "OCR",
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
        output_types: []
      },
      {
        node_type: "end/final",
        display_name: "Workflow End",
        category: "end",
        config_schema: { type: "object", properties: {} },
        input_types: ["text/raw"],
        output_types: []
      }
    ],
    connection_rules: [
      { from_category: "input", to_categories: ["processor", "engine"] },
      { from_category: "processor", to_categories: ["engine", "output"] },
      { from_category: "engine", to_categories: ["output"] },
      { from_category: "output", to_categories: ["end"] }
    ]
  };
}

describe("resolveCompatibleNodeOptions", () => {
  it("returns downstream options by connection_rules category", () => {
    const options = resolveCompatibleNodeOptions({
      anchorNodeType: "input/pdf",
      direction: "downstream",
      registry: buildRegistry()
    });

    expect(options.map((node) => node.node_type)).toEqual([
      "processor/layout_detection",
      "engine/ocr"
    ]);
  });

  it("returns upstream options by reversed connection_rules category", () => {
    const options = resolveCompatibleNodeOptions({
      anchorNodeType: "engine/ocr",
      direction: "upstream",
      registry: buildRegistry()
    });

    expect(options.map((node) => node.node_type)).toEqual([
      "processor/layout_detection",
      "input/pdf"
    ]);
  });

  it("falls back to all nodes when connection_rules are empty", () => {
    const registry = buildRegistry();
    registry.connection_rules = [];

    const options = resolveCompatibleNodeOptions({
      anchorNodeType: "engine/ocr",
      direction: "upstream",
      registry
    });

    expect(options.map((node) => node.node_type)).toEqual([
      "processor/layout_detection",
      "output/markdown",
      "engine/ocr",
      "input/pdf",
      "end/final"
    ]);
  });

  it("exposes user-managed end nodes in endpoint add options", () => {
    const options = resolveCompatibleNodeOptions({
      anchorNodeType: "output/markdown",
      direction: "downstream",
      registry: buildRegistry()
    });

    expect(options.map((node) => node.node_type)).toEqual(["end/final"]);
  });
});

describe("buildEndpointConnection", () => {
  it("creates downstream source->target connection", () => {
    expect(buildEndpointConnection("engine_1", "output_2", "downstream")).toEqual({
      source: "engine_1",
      target: "output_2"
    });
  });

  it("creates upstream source->target connection", () => {
    expect(buildEndpointConnection("engine_1", "input_2", "upstream")).toEqual({
      source: "input_2",
      target: "engine_1"
    });
  });
});

describe("resolveEndpointNodePosition", () => {
  it("places downstream nodes to the right with sibling offset", () => {
    expect(resolveEndpointNodePosition({ x: 200, y: 140 }, "downstream", 2)).toEqual({
      x: 480,
      y: 332
    });
  });

  it("places upstream nodes to the left and clamps negative sibling count", () => {
    expect(resolveEndpointNodePosition({ x: 300, y: 140 }, "upstream", -3)).toEqual({
      x: 20,
      y: 140
    });
  });
});
