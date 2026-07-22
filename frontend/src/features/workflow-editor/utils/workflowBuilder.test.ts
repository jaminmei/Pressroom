import { describe, expect, it } from "vitest";

import { buildWorkflowExecutionPayload, getDirectPredecessors } from "@/features/workflow-editor/utils/workflowBuilder";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

const nodes: WorkflowNode[] = [
  {
    id: "input_1",
    type: "input/pdf",
    data: {
      label: "PDF 輸入",
      config: { dpi: 300 },
      configSchema: { type: "object", properties: {} }
    }
  },
  {
    id: "engine_1",
    type: "engine/ocr",
    data: {
      label: "OCR",
      config: { model: "paddleocr" },
      configSchema: { type: "object", properties: {} }
    }
  },
  {
    id: "output_1",
    type: "output/markdown",
    data: {
      label: "Markdown",
      config: {},
      configSchema: { type: "object", properties: {} }
    }
  }
];

const edges: WorkflowEdge[] = [
  { id: "e1", source: "input_1", target: "engine_1", targetHandle: "input-images" },
  { id: "e2", source: "engine_1", target: "output_1", targetHandle: "input-text" }
];

describe("buildWorkflowExecutionPayload", () => {
  it("builds workflow JSON and ordered files with placeholder mapping", () => {
    const file = new File(["pdf"], "doc.pdf", { type: "application/pdf" });
    const result = buildWorkflowExecutionPayload({
      nodes,
      edges,
      nodeConfigs: {
        input_1: { dpi: 300 },
        engine_1: { model: "paddleocr" },
        output_1: {}
      },
      uploadedFiles: {
        input_1: file
      }
    });

    expect(result.workflow.nodes).toEqual([
      { id: "input_1", type: "input/pdf", config: { dpi: 300, file: "$file_0" } },
      { id: "engine_1", type: "engine/ocr", config: { model: "paddleocr" } },
      { id: "output_1", type: "output/markdown", config: {} }
    ]);
    expect(result.workflow.connections).toEqual([
      { source: "input_1", target: "engine_1", target_port: "images" },
      { source: "engine_1", target: "output_1", target_port: "text" }
    ]);
    expect(result.orderedFiles).toEqual([file]);
  });

  it("supports multiple input nodes and keeps node order", () => {
    const first = new File(["a"], "a.pdf", { type: "application/pdf" });
    const second = new File(["b"], "b.pdf", { type: "application/pdf" });
    const result = buildWorkflowExecutionPayload({
      nodes: [
        nodes[0],
        {
          id: "input_2",
          type: "input/pdf",
          data: {
            label: "PDF 2",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        },
        nodes[1],
        nodes[2]
      ],
      edges: [
        { id: "e1", source: "input_1", target: "engine_1", targetHandle: "input-images" },
        { id: "e2", source: "input_2", target: "engine_1", targetHandle: "input-images" },
        { id: "e3", source: "engine_1", target: "output_1", targetHandle: "input-text" }
      ],
      nodeConfigs: {
        input_1: { dpi: 300 },
        input_2: { dpi: 200 },
        engine_1: { model: "paddleocr" },
        output_1: {}
      },
      uploadedFiles: {
        input_1: first,
        input_2: second
      }
    });

    expect(result.workflow.nodes[0]?.config.file).toBe("$file_0");
    expect(result.workflow.nodes[1]?.config.file).toBe("$file_1");
    expect(result.orderedFiles).toEqual([first, second]);
  });
});

describe("getDirectPredecessors", () => {
  it("returns empty array when node has no predecessors", () => {
    const result = getDirectPredecessors("input_1", edges);
    expect(result).toEqual([]);
  });

  it("returns direct predecessor IDs when node has predecessors", () => {
    const result = getDirectPredecessors("engine_1", edges);
    expect(result).toEqual(["input_1"]);
  });

  it("returns all direct predecessors for nodes with multiple inputs", () => {
    const multiEdges: WorkflowEdge[] = [
      { id: "e1", source: "input_1", target: "engine_1" },
      { id: "e2", source: "input_2", target: "engine_1" },
      { id: "e3", source: "engine_1", target: "output_1" }
    ];
    const result = getDirectPredecessors("engine_1", multiEdges);
    expect(result).toEqual(["input_1", "input_2"]);
  });

  it("handles chain of nodes correctly", () => {
    const result = getDirectPredecessors("output_1", edges);
    expect(result).toEqual(["engine_1"]);
  });

  it("produces connections without port fields when edges have no handles", () => {
    const noHandleEdges: WorkflowEdge[] = [
      { id: "e1", source: "input_1", target: "engine_1" },
      { id: "e2", source: "engine_1", target: "output_1" }
    ];
    const file = new File(["pdf"], "doc.pdf", { type: "application/pdf" });
    const result = buildWorkflowExecutionPayload({
      nodes,
      edges: noHandleEdges,
      nodeConfigs: {
        input_1: { dpi: 300 },
        engine_1: { model: "paddleocr" },
        output_1: {}
      },
      uploadedFiles: { input_1: file }
    });

    expect(result.workflow.connections).toEqual([
      { source: "input_1", target: "engine_1" },
      { source: "engine_1", target: "output_1" }
    ]);
  });
});
