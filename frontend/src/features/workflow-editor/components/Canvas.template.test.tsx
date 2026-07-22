import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import Canvas from "@/features/workflow-editor/components/Canvas";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";

const defaultCanvasProps = {
  onExecuteWorkflow: () => Promise.resolve({ ok: true as const, errors: [] }),
  taskStatus: "idle" as const
};

describe("Canvas template guide", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: null,
      nodeRegistry: {
        nodes: [
          {
            node_type: "input/pdf",
            display_name: "PDF 輸入",
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
            display_name: "Markdown 輸出",
            category: "output",
            config_schema: { type: "object", properties: {} },
            input_types: ["text/raw"],
            output_types: ["text/markdown"],
            max_outputs: 1
          },
          {
            node_type: "end/final",
            display_name: "End",
            category: "end",
            config_schema: { type: "object", properties: {} },
            input_types: ["text/*", "application/yaml"],
            max_inputs: -1,
            max_outputs: 0
          }
        ],
        connection_rules: [{ from_category: "output", to_categories: ["end"] }]
      }
    });
  });

  it("applies template from empty canvas guide", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    expect(screen.getByTestId("empty-canvas-guide")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Apply" })[0]);

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodes).toHaveLength(4);
    });
    expect(useWorkflowStore.getState().edges).toHaveLength(3);
    expect(useWorkflowStore.getState().nodes.some((node) => node.id === "end_1")).toBe(true);
    expect(useWorkflowStore.getState().selectedNodeId).toBe("input_1");
  });

  it("ignores legacy node-type drop when empty canvas guide is visible", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    const emptyGuide = screen.getByTestId("empty-canvas-guide");
    fireEvent.dragOver(emptyGuide, {
      dataTransfer: { dropEffect: "none" }
    });
    fireEvent.drop(emptyGuide, {
      clientX: 180,
      clientY: 220,
      dataTransfer: {
        getData: (format: string) => (format === "text/plain" ? "engine/ocr" : "")
      }
    });

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodes).toHaveLength(0);
    });
  });
});
