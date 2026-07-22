import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ChangeEvent, KeyboardEvent, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Position } from "@xyflow/react";

import InlineAddEdge from "@/features/workflow-editor/components/InlineAddEdge";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

vi.mock("@xyflow/react", () => ({
  BaseEdge: ({ className }: { className?: string }) => (
    <div className={className} data-testid="base-edge" />
  ),
  EdgeLabelRenderer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Position: {
    Left: "left",
    Right: "right"
  },
  getBezierPath: () => ["M 0 0 L 300 0", 150, 60],
  useStoreApi: () => ({
    getState: () => ({
      domNode: null,
      updateNodeInternals: vi.fn()
    })
  })
}));

vi.mock("antd", () => ({
  Input: ({
    placeholder,
    value,
    onChange,
    onKeyDown
  }: {
    placeholder?: string;
    value?: string;
    onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
    onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  }) => (
    <input
      placeholder={placeholder}
      value={value}
      onChange={onChange}
      onKeyDown={onKeyDown}
    />
  ),
  Popover: ({ children, content }: { children: ReactNode; content: ReactNode }) => (
    <div>
      {children}
      {content}
    </div>
  )
}));

describe("InlineAddEdge", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          position: { x: 0, y: 0 },
          data: {
            label: "PDF Input",
            config: {},
            configSchema: { type: "object", properties: {} },
            outputTypes: ["application/pdf"]
          }
        },
        {
          id: "end_1",
          type: "end/final",
          position: { x: 320, y: 0 },
          data: {
            label: "End",
            config: {},
            configSchema: { type: "object", properties: {} },
            inputTypes: ["text/*", "application/yaml"]
          }
        }
      ],
      edges: [{ id: "edge-main", source: "input_1", target: "end_1" }],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: null,
      nodeRegistry: {
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
            node_type: "end/final",
            display_name: "End",
            category: "end",
            config_schema: { type: "object", properties: {} },
            input_types: ["text/*", "application/yaml"],
            max_inputs: -1,
            max_outputs: 0
          }
        ],
        connection_rules: [
          { from_category: "input", to_categories: ["engine", "end"] },
          { from_category: "engine", to_categories: ["end"] }
        ]
      }
    });
  });

  it("inserts a node on the current edge and rewires the connection", async () => {
    render(
      <InlineAddEdge
        data={{}}
        id="edge-main"
        markerEnd={undefined}
        selected={false}
        source="input_1"
        sourcePosition={Position.Right}
        sourceX={100}
        sourceY={60}
        target="end_1"
        targetPosition={Position.Left}
        targetX={300}
        targetY={60}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /OCR Engine/ }));

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodes).toHaveLength(3);
    });

    const state = useWorkflowStore.getState();
    const insertedNode = state.nodes.find((node) => node.type === "engine/ocr");

    expect(insertedNode).toBeTruthy();
    expect(state.edges).toHaveLength(2);
    expect(state.edges.some((edge) => edge.id === "edge-main")).toBe(false);
    expect(
      state.edges.some((edge) => edge.source === "input_1" && edge.target === insertedNode?.id)
    ).toBe(true);
    expect(
      state.edges.some((edge) => edge.source === insertedNode?.id && edge.target === "end_1")
    ).toBe(true);
    expect(state.nodes.some((node) => node.id === "end_1" && node.type === "end/final")).toBe(true);
    expect(state.selectedNodeId).toBe(insertedNode?.id ?? null);
    expect(useUIStore.getState().selectedNodeId).toBe(insertedNode?.id ?? null);
  });

  it("replaces the insert control with a running progress label during execution", () => {
    render(
      <InlineAddEdge
        data={{ executionStatus: "running", hideAddControl: true }}
        id="edge-main"
        markerEnd={undefined}
        selected={false}
        source="input_1"
        sourcePosition={Position.Right}
        sourceX={100}
        sourceY={60}
        target="end_1"
        targetPosition={Position.Left}
        targetX={300}
        targetY={60}
      />
    );

    expect(screen.getByTestId("base-edge")).toHaveClass("workflow-edge--running");
    expect(screen.getByTestId("workflow-edge-status-running")).toHaveTextContent("Running");
    expect(screen.queryByLabelText("Insert a node on this connection")).not.toBeInTheDocument();
  });
});
