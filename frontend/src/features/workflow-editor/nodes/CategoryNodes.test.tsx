import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import EndNode from "@/features/workflow-editor/nodes/EndNode";
import EngineNode from "@/features/workflow-editor/nodes/EngineNode";
import InputNode from "@/features/workflow-editor/nodes/InputNode";
import ProcessorNode from "@/features/workflow-editor/nodes/ProcessorNode";

vi.mock("@xyflow/react", () => ({
  Handle: ({
    children,
    isConnectable,
    position,
    type,
    ...props
  }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
    children?: ReactNode;
    isConnectable?: boolean;
    position: string;
    type: string;
    "data-testid"?: string;
  }) => {
    void isConnectable;

    return (
      <button
        data-testid={props["data-testid"]?.toString() ?? `handle-${type}-${position}`}
        type="button"
        {...props}
      >
        {children}
      </button>
    );
  },
  Position: {
    Left: "left",
    Right: "right"
  },
  useStoreApi: () => ({
    getState: () => ({ domNode: null, updateNodeInternals: vi.fn() })
  })
}));

describe("workflow editor category nodes", () => {
  it.each([
    {
      name: "InputNode",
      Component: InputNode,
      color: "#2ba471"
    },
    {
      name: "ProcessorNode",
      Component: ProcessorNode,
      color: "#6d5efa"
    },
    {
      name: "EngineNode",
      Component: EngineNode,
      color: "#296dff"
    },
    {
      name: "EndNode",
      Component: EndNode,
      color: "#0d9488"
    }
  ])("renders $name with category style, handles, and status badge", ({ Component, color }) => {
    const { container } = render(
      <Component
        data={{
          label: "OCR Engine",
          config: {
            model: "paddleocr",
            language: "auto",
            debug: true
          },
          status: "running"
        }}
        id="node-1"
        isConnectable
      />
    );

    expect(screen.getByTestId("workflow-node-card")).toHaveClass("workflow-node-card");

    expect(screen.getByTestId("workflow-node-title")).toHaveStyle({ backgroundColor: color });
    expect(container.querySelector(".workflow-node-icon svg")).toBeInTheDocument();
    expect(screen.getByText("OCR Engine")).toBeInTheDocument();
    expect(screen.getByTestId("node-status-running")).toBeInTheDocument();

    expect(screen.getByText("model: paddleocr")).toBeInTheDocument();
    expect(screen.getByText("language: auto")).toBeInTheDocument();
    expect(screen.getByText("debug: Yes")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Add upstream node" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add downstream node" })).toBeInTheDocument();
    expect(screen.getByTestId("workflow-node-endpoint-handle-upstream")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-node-endpoint-handle-downstream")).toBeInTheDocument();
  });

  it("renders compact empty config summary when config is missing", () => {
    render(
      <EngineNode
        data={{
          label: "OCR Engine",
          config: {},
          status: "idle"
        }}
        id="node-2"
        isConnectable
      />
    );

    expect(screen.getByText("No config")).toBeInTheDocument();
  });

  it("T-20: renders all config entries without truncation (6 entries)", () => {
    render(
      <EngineNode
        data={{
          label: "Test Node",
          config: {
            model: "paddleocr",
            language: "zh",
            dpi: 300,
            grayscale: true,
            format: "pdf",
            quality: 95
          },
          status: "idle"
        }}
        id="node-3"
        isConnectable
      />
    );

    expect(screen.getByText("model: paddleocr")).toBeInTheDocument();
    expect(screen.getByText("language: zh")).toBeInTheDocument();
    expect(screen.getByText("dpi: 300")).toBeInTheDocument();
    expect(screen.getByText("grayscale: Yes")).toBeInTheDocument();
    expect(screen.getByText("format: pdf")).toBeInTheDocument();
    expect(screen.getByText("quality: 95")).toBeInTheDocument();

    const summaryItems = screen.getAllByText(/:/);
    expect(summaryItems.length).toBeGreaterThanOrEqual(6);
  });

  it("T-27: 'No config' entry does not trigger tooltip (title is undefined)", () => {
    render(
      <EngineNode
        data={{
          label: "Empty Node",
          config: {},
          status: "idle"
        }}
        id="node-empty"
        isConnectable
      />
    );

    const noConfigEl = screen.getByText("No config");
    expect(noConfigEl).toBeInTheDocument();
    // The "No config" text should exist without a tooltip wrapper title attribute
    // Ant Design Tooltip with title={undefined} does not render a tooltip
    expect(noConfigEl.closest("[class*='ant-tooltip']")).toBeNull();
  });

  it("renders all 5 node types correctly", () => {
    const nodeTypes = [
      { Component: InputNode, label: "Input Node" },
      { Component: ProcessorNode, label: "Processor Node" },
      { Component: EngineNode, label: "Engine Node" },
      { Component: EndNode, label: "Output Node" },
      { Component: EndNode, label: "End Node" }
    ];

    for (const { Component, label } of nodeTypes) {
      const { container, unmount } = render(
        <Component
          data={{
            label,
            config: { test_key: "test_value" },
            status: "idle"
          }}
          id={`node-${label}`}
          isConnectable
        />
      );

      expect(container.querySelector(".workflow-node-icon svg")).toBeInTheDocument();
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText("test_key: test_value")).toBeInTheDocument();
      expect(screen.getByTestId("workflow-node-card")).toBeInTheDocument();

      unmount();
    }
  });
});
