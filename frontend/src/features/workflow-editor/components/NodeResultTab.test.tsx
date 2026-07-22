import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import NodeResultTab from "@/features/workflow-editor/components/NodeResultTab";
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
  });

  it("does not request node results without run view permission", () => {
    useWorkspaceStore.setState({ capabilities: [] });
    useTaskExecutionStore.getState().setTaskId("task-denied");
    useTaskExecutionStore.getState().updateNodeStatus("node-denied", "completed");

    render(<NodeResultTab nodeId="node-denied" />);

    expect(mockGetNodeResult).not.toHaveBeenCalled();
    expect(screen.getByTestId("node-result-empty")).toBeInTheDocument();
  });

  it("renders fallback JSON and metadata together with binary previews and layout labels", async () => {
    useTaskExecutionStore.getState().setTaskId("task-1");
    useTaskExecutionStore.getState().updateNodeStatus("node-1", "completed");

    mockGetNodeResult.mockResolvedValue({
      node_id: "node-1",
      node_type: "layout_detection",
      status: "completed",
      output_type: null,
      data: null,
      output: {
        text: null,
        binary: [
          {
            data: "MQ==",
            mime_type: "image/png",
            ref: "",
            size_bytes: 100
          },
          {
            data: "Mg==",
            mime_type: "image/png",
            ref: "",
            size_bytes: 120
          }
        ],
        structured: {
          kind: "layout_regions",
          elements: [{ type: "text" }, { type: "table" }]
        },
        metadata: {
          processing_time_ms: 850
        }
      }
    });

    render(<NodeResultTab nodeId="node-1" />);

    await waitFor(() => {
      expect(screen.getByTestId("binary-image-preview")).toBeInTheDocument();
    });

    expect(screen.getByText(/"kind": "layout_regions"/)).toBeInTheDocument();
    expect(screen.queryByText(/"MQ=="/)).not.toBeInTheDocument();
    expect(screen.getByText("processing_time_ms: 0.8s")).toBeInTheDocument();
    expect(screen.getByText("Region 1 · text")).toBeInTheDocument();
    expect(screen.getByText("Region 2 · table")).toBeInTheDocument();
    expect(screen.getAllByTestId("mock-antd-image")).toHaveLength(2);
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
});
