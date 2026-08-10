import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import NodeResultTab from "@/features/workflow-editor/components/NodeResultTab";
import { setValidatedActiveWorkspaceId } from "@/services/workspaceTransport";
import { useWorkspaceStore } from "@/stores/workspaceStore";

const mockGetNodeResult = vi.fn();

vi.mock("@/services/taskApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/taskApi")>("@/services/taskApi");
  return {
    ...actual,
    getNodeResult: (...args: unknown[]) => mockGetNodeResult(...args)
  };
});

vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
    Image: ({ alt, src, style }: { alt?: string; src: string; style?: React.CSSProperties }) => (
      <img alt={alt ?? ""} data-testid="mock-antd-image" src={src} style={style} />
    )
  };
});

describe("NodeResultTab", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
    mockGetNodeResult.mockReset();
    useWorkspaceStore.setState({ capabilities: ["run.view"] });
    setValidatedActiveWorkspaceId("ws-test");
  });

  it("does not request node results without run view permission", () => {
    useWorkspaceStore.setState({ capabilities: [] });
    useTaskExecutionStore.getState().setTaskId("task-denied");
    useTaskExecutionStore.getState().updateNodeStatus("node-denied", "completed");

    render(<NodeResultTab nodeId="node-denied" />);

    expect(mockGetNodeResult).not.toHaveBeenCalled();
    expect(screen.getByTestId("node-result-empty")).toBeInTheDocument();
  });

  it("renders layout bbox metadata over the upstream source image", async () => {
    useTaskExecutionStore.getState().setTaskId("task-1");
    useTaskExecutionStore.getState().updateNodeStatus("node-1", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-1",
      node_type: "processor/layout_detection",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          kind: "layout_regions",
          elements: [
            {
              id: "layout_0",
              type: "Text",
              bbox: { x: 10, y: 20, width: 200, height: 80 },
              confidence: 0.95
            },
            {
              id: "layout_1",
              type: "Table",
              bbox: { x: 10, y: 120, width: 240, height: 160 },
              confidence: 0.9
            }
          ],
          total_regions: 2
        },
        metadata: {
          processing_time_ms: 850
        }
      }
    });

    render(<NodeResultTab nodeId="node-1" />);

    await waitFor(() => {
      expect(screen.getAllByText("Text").length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText("Table").length).toBeGreaterThan(0);
    expect(screen.getByAltText("Layout detection source")).toBeInTheDocument();
    expect(screen.queryByTestId("binary-image-preview")).not.toBeInTheDocument();
    expect(screen.getByText("processing_time_ms: 0.8s")).toBeInTheDocument();
  });

  it("keeps the JSON fallback only when binary is empty", async () => {
    useTaskExecutionStore.getState().setTaskId("task-2");
    useTaskExecutionStore.getState().updateNodeStatus("node-2", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-2",
      node_type: "engine/example",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          summary: "only json"
        },
        metadata: {}
      }
    });

    render(<NodeResultTab nodeId="node-2" />);

    await waitFor(() => {
      expect(screen.getByText(/"summary": "only json"/)).toBeInTheDocument();
    });

    expect(screen.queryByTestId("binary-image-preview")).not.toBeInTheDocument();
  });

  it("renders iteration_result outputs with derived summary, status badges, and per-item detail toggles", async () => {
    useTaskExecutionStore.getState().setTaskId("task-3");
    useTaskExecutionStore.getState().updateNodeStatus("node-3", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-3",
      node_type: "processor/iteration",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          kind: "iteration_result",
          items: [
            {
              index: 0,
              status: "success",
              error: null,
              output: { text: "first item" }
            },
            {
              index: 1,
              status: "error",
              error: "timeout",
              output: null
            }
          ]
        },
        metadata: {
          engine: "engine/ocr",
          mode: "sequential"
        }
      }
    });

    render(<NodeResultTab nodeId="node-3" />);

    await waitFor(() => {
      expect(screen.getByTestId("node-result-iteration")).toBeInTheDocument();
    });

    expect(screen.getByText("Total items")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
    expect(screen.getByText("Item 0")).toBeInTheDocument();
    expect(screen.getByText("Item 1")).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Output detail")[0]);

    await waitFor(() => {
      expect(screen.getByText(/"text": "first item"/)).toBeInTheDocument();
    });
  });

  it("prefers adaptor provenance from input_sources and hides generic adaptor metadata", async () => {
    useTaskExecutionStore.getState().setTaskId("task-4");
    useTaskExecutionStore.getState().updateNodeStatus("node-4", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-4",
      node_type: "processor/adaptor",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: { result: "ok" },
        metadata: {
          input_sources: {
            image: {
              node_id: "layout_1",
              output_path: ["structured", "elements", "hero"],
              secret: "redacted"
            }
          },
          secret_token: "should-not-render",
          upstream_latency_ms: 9
        }
      }
    });

    render(<NodeResultTab nodeId="node-4" />);

    await waitFor(() => {
      expect(screen.getByText("Input Sources")).toBeInTheDocument();
    });

    expect(screen.getByTestId("adaptor-input-sources-table")).toBeInTheDocument();
    expect(screen.getByText("image")).toBeInTheDocument();
    expect(screen.getByText("layout_1")).toBeInTheDocument();
    expect(screen.getByText("structured.elements.hero")).toBeInTheDocument();
    expect(screen.queryByText(/secret_token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/should-not-render/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/upstream_latency_ms/i)).not.toBeInTheDocument();
  });

  it("ignores malformed adaptor metadata safely and falls back to structured _binding_source", async () => {
    useTaskExecutionStore.getState().setTaskId("task-5");
    useTaskExecutionStore.getState().updateNodeStatus("node-5", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-5",
      node_type: "processor/adaptor",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          page: {
            metadata: {
              _binding_source: {
                node_id: "input_2",
                output_path: ["text"]
              }
            }
          }
        },
        metadata: {
          input_sources: {
            broken: {
              node_id: 42,
              output_path: "text"
            }
          }
        }
      }
    });

    render(<NodeResultTab nodeId="node-5" />);

    await waitFor(() => {
      expect(screen.getByTestId("adaptor-input-sources-table")).toBeInTheDocument();
    });

    expect(screen.getByText("page")).toBeInTheDocument();
    expect(screen.getByText("input_2")).toBeInTheDocument();
    expect(screen.getByText("text")).toBeInTheDocument();
    expect(screen.queryByText("broken")).not.toBeInTheDocument();
  });

  it("does not leak adaptor metadata in fallback JSON when structured output is absent", async () => {
    useTaskExecutionStore.getState().setTaskId("task-8");
    useTaskExecutionStore.getState().updateNodeStatus("node-8", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-8",
      node_type: "processor/adaptor",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: "adapted text",
        binary: [
          {
            data: "AQID",
            mime_type: "image/png",
            ref: "",
            size_bytes: 4
          }
        ],
        structured: null,
        metadata: {
          input_sources: {
            hero: {
              node_id: "layout_1",
              output_path: ["structured", "elements", "hero"]
            }
          },
          secret_token: "top-secret",
          private_endpoint: "https://private.example.internal"
        }
      }
    });

    render(<NodeResultTab nodeId="node-8" />);

    await waitFor(() => {
      expect(screen.getByTestId("adaptor-input-sources-table")).toBeInTheDocument();
    });

    expect(screen.getByText("hero")).toBeInTheDocument();
    expect(screen.getByText("layout_1")).toBeInTheDocument();
    expect(screen.getByText("structured.elements.hero")).toBeInTheDocument();
    expect(screen.getByText(/"text": "adapted text"/)).toBeInTheDocument();
    expect(screen.queryByText(/secret_token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/top-secret/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/private_endpoint/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/private\.example\.internal/i)).not.toBeInTheDocument();
  });

  it("uses explicit iteration counts when provided and keeps detail output scroll bounded", async () => {
    useTaskExecutionStore.getState().setTaskId("task-6");
    useTaskExecutionStore.getState().updateNodeStatus("node-6", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-6",
      node_type: "processor/iteration",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          kind: "iteration_result",
          total: 9,
          success_count: 7,
          error_count: 2,
          items: [{ index: 8, status: "success", output: { payload: "x".repeat(800) } }]
        },
        metadata: {
          mode: "parallel"
        }
      }
    });

    render(<NodeResultTab nodeId="node-6" />);

    await waitFor(() => {
      expect(screen.getByTestId("node-result-iteration")).toBeInTheDocument();
    });

    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Output detail"));

    await waitFor(() => {
      const detail = screen.getByText(/"payload":/).closest("pre");
      expect(detail).toHaveStyle({ maxHeight: "240px", overflow: "auto" });
    });
  });

  it("handles malformed or empty iteration items safely", async () => {
    useTaskExecutionStore.getState().setTaskId("task-7");
    useTaskExecutionStore.getState().updateNodeStatus("node-7", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-7",
      node_type: "processor/iteration",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [],
        structured: {
          kind: "iteration_result",
          items: null
        },
        metadata: {}
      }
    });

    render(<NodeResultTab nodeId="node-7" />);

    await waitFor(() => {
      expect(screen.getByText("No iteration items recorded")).toBeInTheDocument();
    });
  });
});
