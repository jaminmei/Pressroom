import { describe, expect, it } from "vitest";

import EngineNode from "@/features/workflow-editor/nodes/EngineNode";
import InputNode from "@/features/workflow-editor/nodes/InputNode";
import ProcessorNode from "@/features/workflow-editor/nodes/ProcessorNode";
import { resolveWorkflowNodeComponentType, workflowNodeTypes } from "@/features/workflow-editor/nodes/nodeTypes";

describe("workflow node types registry", () => {
  it("maps workflow node type prefixes to custom node components", () => {
    expect(resolveWorkflowNodeComponentType("input/pdf")).toBe("inputNode");
    expect(resolveWorkflowNodeComponentType("processor/layout_detection")).toBe("processorNode");
    expect(resolveWorkflowNodeComponentType("engine/ocr")).toBe("engineNode");
    expect(resolveWorkflowNodeComponentType("output/markdown")).toBe("processorNode");
    expect(resolveWorkflowNodeComponentType("end/final")).toBe("endNode");
  });

  it("falls back to processor node for unknown category", () => {
    expect(resolveWorkflowNodeComponentType("custom/unknown")).toBe("processorNode");
  });

  it("registers all workflow node components for React Flow", () => {
    expect(workflowNodeTypes).toMatchObject({
      inputNode: InputNode,
      processorNode: ProcessorNode,
      engineNode: EngineNode,
      endNode: expect.any(Function)
    });
    expect(workflowNodeTypes).toHaveProperty("endNode");
  });
});
