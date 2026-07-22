import { describe, expect, it } from "vitest";

import {
  getHandleLabel,
  HANDLE_ID_CONTEXT,
  HANDLE_ID_PRIMARY,
  isMultiInputNode,
  resolveTargetHandle,
  resolveTargetHandleForEdge
} from "@/features/workflow-editor/utils/handleRouting";
import type { NodeRegistryNode } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";

describe("isMultiInputNode", () => {
  it("returns true when maxInputs is -1", () => {
    expect(isMultiInputNode(-1)).toBe(true);
  });

  it("returns false when maxInputs is undefined", () => {
    expect(isMultiInputNode(undefined)).toBe(false);
  });

  it("returns false when maxInputs is 0", () => {
    expect(isMultiInputNode(0)).toBe(false);
  });

  it("returns false when maxInputs is 1", () => {
    expect(isMultiInputNode(1)).toBe(false);
  });

  it("returns false when maxInputs is a positive number", () => {
    expect(isMultiInputNode(3)).toBe(false);
  });
});

describe("resolveTargetHandle", () => {
  it("returns undefined for non-multi-input nodes", () => {
    expect(resolveTargetHandle(["image/png"], 1)).toBeUndefined();
    expect(resolveTargetHandle(["image/png"], undefined)).toBeUndefined();
  });

  it("routes image/* to primary handle", () => {
    expect(resolveTargetHandle(["image/png"], -1)).toBe(HANDLE_ID_PRIMARY);
    expect(resolveTargetHandle(["image/jpeg"], -1)).toBe(HANDLE_ID_PRIMARY);
    expect(resolveTargetHandle(["image/*"], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("routes text/raw to primary handle", () => {
    expect(resolveTargetHandle(["text/raw"], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("routes text/plain to primary handle", () => {
    expect(resolveTargetHandle(["text/plain"], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("routes application/x-layout-result to primary handle", () => {
    expect(resolveTargetHandle(["application/x-layout-result"], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("routes mixed types to primary handle", () => {
    expect(resolveTargetHandle(["image/png", "text/raw"], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("returns primary handle for empty output types", () => {
    expect(resolveTargetHandle([], -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("returns primary handle for undefined output types", () => {
    expect(resolveTargetHandle(undefined, -1)).toBe(HANDLE_ID_PRIMARY);
  });

  it("routes application/pdf to primary handle", () => {
    expect(resolveTargetHandle(["application/pdf"], -1)).toBe(HANDLE_ID_PRIMARY);
  });
});

describe("resolveTargetHandleForEdge", () => {
  const registryNodes: NodeRegistryNode[] = [
    {
      node_type: "input/image",
      display_name: "Image Input",
      category: "input",
      config_schema: { type: "object", properties: {} },
      output_types: ["image/*"],
      max_inputs: 0,
      max_outputs: -1
    },
    {
      node_type: "processor/layout_detection",
      display_name: "Layout Detection",
      category: "processor",
      config_schema: { type: "object", properties: {} },
      input_types: ["image/*"],
      output_types: ["application/x-layout-result"],
      max_inputs: 1,
      max_outputs: -1
    },
    {
      node_type: "engine/model",
      display_name: "VLM Model",
      category: "engine",
      config_schema: { type: "object", properties: {} },
      input_types: ["image/*", "text/raw", "application/x-layout-result"],
      output_types: ["text/raw"],
      max_inputs: -1,
      max_outputs: -1
    }
  ];

  const nodes: WorkflowNode[] = [
    {
      id: "input_1",
      type: "input/image",
      data: {
        label: "Image Input",
        config: {},
        configSchema: { type: "object", properties: {} },
        outputTypes: ["image/*"],
        maxInputs: 0
      }
    },
    {
      id: "processor_1",
      type: "processor/layout_detection",
      data: {
        label: "Layout Detection",
        config: {},
        configSchema: { type: "object", properties: {} },
        outputTypes: ["application/x-layout-result"],
        maxInputs: 1
      }
    },
    {
      id: "engine_1",
      type: "engine/model",
      data: {
        label: "VLM Model",
        config: {},
        configSchema: { type: "object", properties: {} },
        inputTypes: ["image/*", "text/raw", "application/x-layout-result"],
        maxInputs: -1
      }
    }
  ];

  it("returns primary handle for image source to engine", () => {
    const handle = resolveTargetHandleForEdge(
      "input_1",
      "engine_1",
      nodes,
      registryNodes
    );
    expect(handle).toBe(HANDLE_ID_PRIMARY);
  });

  it("returns primary handle for layout detection source to engine", () => {
    const handle = resolveTargetHandleForEdge(
      "processor_1",
      "engine_1",
      nodes,
      registryNodes
    );
    expect(handle).toBe(HANDLE_ID_PRIMARY);
  });

  it("returns undefined for non-multi-input target", () => {
    const handle = resolveTargetHandleForEdge(
      "input_1",
      "processor_1",
      nodes,
      registryNodes
    );
    expect(handle).toBeUndefined();
  });

  it("returns undefined for unknown target node", () => {
    const handle = resolveTargetHandleForEdge(
      "input_1",
      "nonexistent",
      nodes,
      registryNodes
    );
    expect(handle).toBeUndefined();
  });

  it("returns primary handle for unknown source node", () => {
    const handle = resolveTargetHandleForEdge(
      "nonexistent",
      "engine_1",
      nodes,
      registryNodes
    );
    expect(handle).toBe(HANDLE_ID_PRIMARY);
  });
});

describe("getHandleLabel", () => {
  it("returns 'Primary' for primary handle id", () => {
    expect(getHandleLabel(HANDLE_ID_PRIMARY)).toBe("Primary");
  });

  it("returns 'Context' for context handle id", () => {
    expect(getHandleLabel(HANDLE_ID_CONTEXT)).toBe("Context");
  });

  it("returns 'Primary' for undefined", () => {
    expect(getHandleLabel(undefined)).toBe("Primary");
  });

  it("returns 'Primary' for unknown handle id", () => {
    expect(getHandleLabel("unknown-handle")).toBe("Primary");
  });
});
