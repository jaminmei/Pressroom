import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Canvas from "@/features/workflow-editor/components/Canvas";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";

const defaultCanvasProps = {
  onExecuteWorkflow: () => Promise.resolve({ ok: true as const, errors: [] }),
  taskStatus: "idle" as const
};

const { reactFlowState } = vi.hoisted(() => ({
  reactFlowState: {
    latestProps: null as Record<string, unknown> | null
  }
}));

vi.mock("@xyflow/react", () => {
  type MockNode = { id: string; className?: string };
  interface MockReactFlowProps extends PropsWithChildren {
    nodes?: MockNode[];
    onNodeClick?: (event: unknown, node: MockNode) => void;
    onSelectionChange?: (payload: { nodes: MockNode[]; edges: unknown[] }) => void;
    onPaneClick?: (event: unknown) => void;
    [key: string]: unknown;
  }

  return {
    MarkerType: {
      ArrowClosed: "arrow-closed"
    },
    Position: {
      Left: "left",
      Right: "right",
      Top: "top"
    },
    SelectionMode: {
      Partial: "partial",
      Full: "full"
    },
    ReactFlow: ({
      children,
      nodes = [],
      onNodeClick,
      onSelectionChange,
      onPaneClick,
      ...rest
    }: MockReactFlowProps) => {
      reactFlowState.latestProps = { nodes, onNodeClick, onSelectionChange, onPaneClick, ...rest };
      return (
        <div data-testid="reactflow-mock">
          <button
            data-testid="rf-trigger-selection"
            onClick={() => {
              onSelectionChange?.({ nodes: nodes.slice(0, 2), edges: [] });
            }}
            type="button"
          >
            Trigger Selection
          </button>
          <button
            data-testid="rf-pane-click"
            onClick={(event) => {
              onPaneClick?.(event);
            }}
            type="button"
          >
            Pane Click
          </button>
          {nodes.map((node) => (
            <button
              className={node.className}
              data-testid={`rf-node-${node.id}`}
              key={node.id}
              onClick={(event) => {
                onNodeClick?.(event, node);
              }}
              type="button"
            >
              {node.id}
            </button>
          ))}
          {children}
        </div>
      );
    },
    Background: () => <div data-testid="rf-background" />,
    Controls: ({ children }: PropsWithChildren) => <div data-testid="rf-controls">{children}</div>,
    ControlButton: ({ children, ...props }: PropsWithChildren<Record<string, unknown>>) => <button data-testid="rf-control-button" {...props}>{children}</button>,
    MiniMap: () => <div data-testid="rf-minimap" />,
    useStoreApi: () => ({
      getState: () => ({
        domNode: null,
        updateNodeInternals: vi.fn()
      })
    })
  };
});

function seedWorkflowStore() {
  useTaskExecutionStore.getState().reset();
  useWorkflowStore.setState({
    nodes: [
      {
        id: "input_1",
        type: "input/file",
        position: { x: 40, y: 60 },
        data: {
          label: "Input 1",
          config: {},
          configSchema: { type: "object", properties: {} },
          outputTypes: ["file"]
        }
      },
      {
        id: "engine_1",
        type: "engine/ocr",
        position: { x: 280, y: 170 },
        data: {
          label: "Engine 1",
          config: {},
          configSchema: { type: "object", properties: {} },
          inputTypes: ["file"],
          outputTypes: ["text"]
        }
      },
      {
        id: "output_1",
        type: "output/markdown",
        position: { x: 520, y: 260 },
        data: {
          label: "Output 1",
          config: {},
          configSchema: { type: "object", properties: {} },
          inputTypes: ["text"]
        }
      }
    ],
    edges: [
      { id: "edge-1", source: "input_1", target: "engine_1" },
      { id: "edge-2", source: "engine_1", target: "output_1" }
    ],
    nodeConfigs: {
      input_1: {},
      engine_1: {},
      output_1: {}
    },
    uploadedFiles: {},
    selectedNodeId: null,
    nodeRegistry: {
      nodes: [
        {
          node_type: "input/file",
          display_name: "Input 1",
          category: "input",
          config_schema: { type: "object", properties: {} },
          output_types: ["file"]
        },
        {
          node_type: "engine/ocr",
          display_name: "Engine 1",
          category: "engine",
          config_schema: { type: "object", properties: {} },
          input_types: ["file"],
          output_types: ["text"]
        },
        {
          node_type: "output/markdown",
          display_name: "Output 1",
          category: "output",
          config_schema: { type: "object", properties: {} },
          input_types: ["text"],
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
        { from_category: "input", to_categories: ["engine", "output"] },
        { from_category: "engine", to_categories: ["output"] },
        { from_category: "output", to_categories: ["end"] }
      ]
    }
  });
}

describe("Canvas multi-select and batch actions", () => {
  beforeEach(() => {
    seedWorkflowStore();
    reactFlowState.latestProps = null;
    vi.restoreAllMocks();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
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
  });

  it("projects live node progress onto incoming workflow edges", () => {
    useTaskExecutionStore.setState({
      taskStatus: "running",
      nodeStatuses: {
        input_1: "completed",
        engine_1: "running",
        output_1: "pending"
      }
    });

    render(<Canvas {...defaultCanvasProps} taskStatus="running" />);

    const renderedEdges = reactFlowState.latestProps?.edges as Array<{
      id: string;
      data: { executionStatus: string; hideAddControl: boolean };
      markerEnd: { color: string };
    }>;

    expect(renderedEdges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "edge-1",
          data: expect.objectContaining({
            executionStatus: "running",
            hideAddControl: true
          }),
          markerEnd: expect.objectContaining({ color: "#1677ff" })
        }),
        expect.objectContaining({
          id: "edge-2",
          data: expect.objectContaining({
            executionStatus: "pending",
            hideAddControl: true
          }),
          markerEnd: expect.objectContaining({ color: "#aeb7c6" })
        })
      ])
    );
  });

  it("enables partial selection mode and highlights selected nodes", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    expect(reactFlowState.latestProps).not.toBeNull();
    expect(reactFlowState.latestProps?.selectionMode).toBe("partial");
    expect(reactFlowState.latestProps?.selectionKeyCode).toBe("Shift");

    fireEvent.click(screen.getByTestId("rf-trigger-selection"));

    await waitFor(() => {
      expect(useWorkflowStore.getState().selectedNodeId).toBe("input_1");
    });
    expect(screen.getByTestId("rf-node-input_1")).toHaveClass("workflow-node-selected");
    expect(screen.getByTestId("rf-node-engine_1")).toHaveClass("workflow-node-selected");
    expect(screen.getByTestId("canvas-batch-toolbar")).toBeInTheDocument();
  });

  it("supports Ctrl/Cmd+click toggle and Escape to clear selection", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    fireEvent.click(screen.getByTestId("rf-node-input_1"));
    fireEvent.click(screen.getByTestId("rf-node-engine_1"), { ctrlKey: true });

    await waitFor(() => {
      expect(screen.getByTestId("rf-node-input_1")).toHaveClass("workflow-node-selected");
      expect(screen.getByTestId("rf-node-engine_1")).toHaveClass("workflow-node-selected");
    });
    expect(screen.getByTestId("canvas-batch-toolbar")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("rf-node-input_1"), { metaKey: true });

    await waitFor(() => {
      expect(screen.getByTestId("rf-node-input_1")).not.toHaveClass("workflow-node-selected");
      expect(useWorkflowStore.getState().selectedNodeId).toBe("engine_1");
    });

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(useWorkflowStore.getState().selectedNodeId).toBeNull();
    });
  });

  it("batch deletes selected nodes after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Canvas {...defaultCanvasProps} />);

    fireEvent.click(screen.getByTestId("rf-trigger-selection"));

    await waitFor(() => {
      expect(screen.getByTestId("canvas-batch-toolbar")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() => {
      const state = useWorkflowStore.getState();
      // input_1 and engine_1 are deleted; the legacy output is normalized away.
      expect(state.nodes.find((n) => n.id === "input_1")).toBeUndefined();
      expect(state.nodes.find((n) => n.id === "engine_1")).toBeUndefined();
      expect(state.nodes.find((n) => n.id === "output_1")).toBeUndefined();
      expect(state.nodes).toHaveLength(0);
    });
  });

  it("batch duplicates selected nodes", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    fireEvent.click(screen.getByTestId("rf-trigger-selection"));

    await waitFor(() => {
      expect(screen.getByTestId("canvas-batch-toolbar")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Duplicate"));

    await waitFor(() => {
      const state = useWorkflowStore.getState();
      // The legacy output is normalized away; two originals and two duplicates remain.
      expect(state.nodes).toHaveLength(4);
    });
  });

  it("aligns selected nodes horizontally and vertically", async () => {
    render(<Canvas {...defaultCanvasProps} />);

    fireEvent.click(screen.getByTestId("rf-trigger-selection"));

    await waitFor(() => {
      expect(screen.getByTestId("canvas-batch-toolbar")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Align H"));

    await waitFor(() => {
      const state = useWorkflowStore.getState();
      const [a, b] = state.nodes;
      expect(a.position!.y).toBe(b.position!.y);
    });
  });
});
