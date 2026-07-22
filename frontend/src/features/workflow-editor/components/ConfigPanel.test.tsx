import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConfigPanel from "@/features/workflow-editor/components/ConfigPanel";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { NodeConfigSchema } from "@/types/node-registry";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
});

const inputSchema: NodeConfigSchema = {
  type: "object",
  properties: {
    dpi: {
      type: "integer",
      default: 300,
      minimum: 72,
      maximum: 600
    },
    file: {
      type: "file",
      accept: ["application/pdf"],
      max_size_mb: 50
    }
  },
  required: ["file"]
};

function buildFile() {
  return new File(["pdf"], "spec.pdf", { type: "application/pdf" });
}

describe("ConfigPanel", () => {
  beforeEach(() => {
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          data: {
            label: "PDF 輸入",
            config: { dpi: 300 },
            configSchema: inputSchema,
            inputTypes: [],
            outputTypes: ["application/pdf"]
          }
        },
        {
          id: "output_1",
          type: "output/markdown",
          data: {
            label: "Markdown 輸出",
            config: {},
            configSchema: {
              type: "object",
              properties: {}
            },
            inputTypes: ["text/raw"],
            outputTypes: ["text/markdown"]
          }
        }
      ],
      edges: [{ id: "e1", source: "input_1", target: "output_1" }],
      nodeConfigs: {
        input_1: { dpi: 300 },
        output_1: {}
      },
      uploadedFiles: {
        input_1: buildFile()
      },
      selectedNodeId: null,
      nodeRegistry: {
        nodes: [
          {
            node_type: "input/pdf",
            display_name: "PDF 輸入",
            category: "input",
            config_schema: inputSchema,
            output_types: ["application/pdf"]
          },
          {
            node_type: "output/markdown",
            display_name: "Markdown 輸出",
            category: "output",
            config_schema: {
              type: "object",
              properties: {}
            },
            input_types: ["text/raw"],
            output_types: ["text/markdown"],
            max_outputs: 1
          },
          {
            node_type: "end/final",
            display_name: "End",
            category: "end",
            config_schema: {
              type: "object",
              properties: {}
            },
            input_types: ["text/*", "application/yaml"],
            max_inputs: -1,
            max_outputs: 0
          }
        ],
        connection_rules: [{ from_category: "output", to_categories: ["end"] }]
      }
    });
  });

  it("shows empty prompt when no node is selected", () => {
    render(<ConfigPanel />);
    expect(screen.getByTestId("config-panel-empty")).toBeInTheDocument();
    expect(screen.getByText("Select a node to configure it")).toBeInTheDocument();
  });

  it("syncs form value change to WorkflowStore", () => {
    useWorkflowStore.getState().selectNode("input_1");

    render(<ConfigPanel />);

    const dpiInput = screen.getByRole("spinbutton");
    fireEvent.change(dpiInput, { target: { value: "240" } });
    fireEvent.blur(dpiInput);

    expect(useWorkflowStore.getState().nodeConfigs.input_1).toMatchObject({ dpi: 240 });
  });

  it("deletes selected node and linked edges/files after confirmation", async () => {
    useWorkflowStore.getState().selectNode("input_1");

    render(<ConfigPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Delete node" }));
    expect(await screen.findByText("Delete this node?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    const state = useWorkflowStore.getState();
    expect(state.nodes.find((node) => node.id === "input_1")).toBeUndefined();
    expect(state.nodes).toEqual([]);
    expect(state.edges).toEqual([]);
    expect(state.uploadedFiles.input_1).toBeUndefined();
  });

  it("opens delete confirmation with Delete keyboard key", async () => {
    useWorkflowStore.getState().selectNode("input_1");

    render(<ConfigPanel />);

    fireEvent.keyDown(window, { key: "Delete" });
    expect(await screen.findByText("Delete this node?")).toBeInTheDocument();
  });
});
