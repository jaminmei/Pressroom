import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NodeEndpointAddControl from "@/features/workflow-editor/components/NodeEndpointAddControl";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

vi.mock("@xyflow/react", () => ({
  Handle: ({
    children,
    isConnectable,
    position,
    type: handleType,
    ...props
  }: {
    children?: ReactNode;
    isConnectable?: boolean;
    position?: unknown;
    type?: string;
  } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type">) => {
    void isConnectable;
    void position;
    void handleType;

    return (
      <button type="button" {...props}>
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

describe("NodeEndpointAddControl", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          position: { x: 120, y: 160 },
          data: {
            label: "PDF 輸入",
            config: {},
            configSchema: { type: "object", properties: {} },
            outputTypes: ["application/pdf"]
          }
        },
        {
          id: "engine_1",
          type: "engine/ocr",
          position: { x: 460, y: 160 },
          data: {
            label: "OCR Engine",
            config: {},
            configSchema: { type: "object", properties: {} },
            inputTypes: ["application/pdf"],
            outputTypes: ["text/raw"]
          }
        },
        {
          id: "output_1",
          type: "output/markdown",
          position: { x: 780, y: 160 },
          data: {
            label: "Markdown 輸出",
            config: {},
            configSchema: { type: "object", properties: {} },
            inputTypes: ["text/raw"],
            outputTypes: ["text/markdown"]
          }
        }
      ],
      edges: [
        { id: "e-input_1-engine_1", source: "input_1", target: "engine_1" },
        { id: "e-engine_1-output_1", source: "engine_1", target: "output_1" }
      ],
      nodeConfigs: {
        input_1: {},
        engine_1: {},
        output_1: {}
      },
      uploadedFiles: {},
      selectedNodeId: "input_1",
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
        connection_rules: [
          { from_category: "input", to_categories: ["engine"] },
          { from_category: "engine", to_categories: ["output"] },
          { from_category: "output", to_categories: ["end"] }
        ]
      }
    });
  });

  it("opens searchable endpoint menu and adds a compatible downstream node", async () => {
    render(<NodeEndpointAddControl direction="downstream" nodeId="input_1" nodeType="input/pdf" />);

    fireEvent.click(screen.getByRole("button", { name: "Add downstream node" }));

    const searchInput = await screen.findByPlaceholderText("Search downstream nodes");
    expect(screen.getByRole("button", { name: /OCR Engine/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Model Engine/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /PDF 輸入/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Markdown 輸出/ })).not.toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: "model" } });
    expect(screen.getByRole("button", { name: /Model Engine/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /OCR Engine/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Model Engine/ }));

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodes).toHaveLength(3);
    });

    const state = useWorkflowStore.getState();
    expect(state.nodes.find((node) => node.id === "engine_model_4")?.type).toBe("engine/model");
    expect(state.edges).toHaveLength(2);
    expect(
      state.edges.some((edge) => edge.source === "input_1" && edge.target === "engine_model_4")
    ).toBe(true);
    expect(state.nodes.some((node) => node.type === "end/final")).toBe(false);
    expect(state.nodes.some((node) => node.id === "output_1")).toBe(false);
    expect(state.selectedNodeId).toBe("engine_model_4");
    expect(useUIStore.getState().selectedNodeId).toBe("engine_model_4");
  });
});
