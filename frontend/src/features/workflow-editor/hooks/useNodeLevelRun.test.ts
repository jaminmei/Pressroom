import { act, renderHook } from "@testing-library/react";
import { message } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useNodeLevelRun } from "@/features/workflow-editor/hooks/useNodeLevelRun";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { buildWorkflowExecutionPayload } from "@/features/workflow-editor/utils/workflowBuilder";
import { getTaskResults } from "@/services/taskApi";
import { buildNodeRunTaskFormData, createNodeRunTask } from "@/services/workflowApi";
import { initialUIState, useUIStore } from "@/stores/uiStore";

vi.mock("antd", () => ({
  message: {
    warning: vi.fn(),
    error: vi.fn()
  }
}));

vi.mock("@/features/workflow-editor/utils/workflowBuilder", () => ({
  buildWorkflowExecutionPayload: vi.fn(),
  getDirectPredecessors: vi.fn((nodeId: string, edges: Array<{ source: string; target: string }>) =>
    edges.filter((e) => e.target === nodeId).map((e) => e.source)
  )
}));

vi.mock("@/services/workflowApi", () => ({
  buildNodeRunTaskFormData: vi.fn(),
  createNodeRunTask: vi.fn()
}));

vi.mock("@/services/taskApi", () => ({
  getTaskResults: vi.fn()
}));

describe("useNodeLevelRun", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useUIStore.setState({ ...initialUIState });
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/text",
          data: { label: "input", config: {}, configSchema: { type: "object", properties: {} } }
        },
        {
          id: "engine_1",
          type: "engine/ocr",
          data: { label: "ocr", config: {}, configSchema: { type: "object", properties: {} } }
        }
      ],
      edges: [{ id: "e1", source: "input_1", target: "engine_1" }],
      nodeConfigs: {
        input_1: {},
        engine_1: {}
      },
      uploadedFiles: {
        input_1: new File(["hello"], "input.txt", { type: "text/plain" })
      },
      selectedNodeId: null
    });

    vi.mocked(buildWorkflowExecutionPayload).mockReturnValue({
      workflow: { nodes: [], connections: [] },
      orderedFiles: [new File(["hello"], "input.txt", { type: "text/plain" })]
    } as never);
    vi.mocked(buildNodeRunTaskFormData).mockReturnValue(new FormData());
  });

  it("returns false when target node is an output node", async () => {
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/text",
          data: { label: "input", config: {}, configSchema: { type: "object", properties: {} } }
        },
        {
          id: "output_1",
          type: "output/markdown",
          data: { label: "output", config: {}, configSchema: { type: "object", properties: {} } }
        }
      ],
      edges: [{ id: "e1", source: "input_1", target: "output_1" }],
      nodeConfigs: { input_1: {}, output_1: {} },
      uploadedFiles: { input_1: new File(["hello"], "input.txt", { type: "text/plain" }) },
      selectedNodeId: null
    });
    const { result } = renderHook(() => useNodeLevelRun());

    let success = true;
    await act(async () => {
      success = await result.current.runNode("output_1");
    });

    expect(success).toBe(false);
    expect(message.warning).toHaveBeenCalledWith("Output nodes cannot be run individually.");
    expect(createNodeRunTask).not.toHaveBeenCalled();
  });

  it("returns false when no uploaded files are available", async () => {
    vi.mocked(buildWorkflowExecutionPayload).mockReturnValue({
      workflow: { nodes: [], connections: [] },
      orderedFiles: []
    } as never);
    // Mark predecessor as completed so engine node can run
    useTaskExecutionStore.getState().updateNodeStatus("input_1", "completed");
    const { result } = renderHook(() => useNodeLevelRun());

    let success = true;
    await act(async () => {
      success = await result.current.runNode("engine_1");
    });

    expect(success).toBe(false);
    expect(message.warning).toHaveBeenCalledWith("Upload an input file before running this node.");
    expect(createNodeRunTask).not.toHaveBeenCalled();
  });

  it("creates node-run task and updates stores for non-terminal status", async () => {
    vi.mocked(createNodeRunTask).mockResolvedValue({
      task_id: "task_1",
      status: "running",
      node_id: "engine_1",
      output_format: "markdown"
    });
    // Mark predecessor as completed so engine node can run
    useTaskExecutionStore.getState().updateNodeStatus("input_1", "completed");
    const { result } = renderHook(() => useNodeLevelRun());

    let success = false;
    await act(async () => {
      success = await result.current.runNode("engine_1");
    });

    expect(success).toBe(true);
    expect(createNodeRunTask).toHaveBeenCalledTimes(1);
    expect(getTaskResults).not.toHaveBeenCalled();

    const executionState = useTaskExecutionStore.getState();
    expect(executionState.currentTaskId).toBe("task_1");
    expect(executionState.taskStatus).toBe("running");
    expect(executionState.nodeStatuses.engine_1).toBe("pending");
    expect(useUIStore.getState().rightPanelTab).toBe("run");
    expect(executionState.eventLogs.some((entry) => entry.message.includes("task_1"))).toBe(true);
  });

  it("loads task results when create response is terminal", async () => {
    vi.mocked(createNodeRunTask).mockResolvedValue({
      task_id: "task_2",
      status: "completed",
      node_id: "engine_1",
      output_format: "markdown"
    });
    // Mark predecessor as completed so engine node can run
    useTaskExecutionStore.getState().updateNodeStatus("input_1", "completed");
    vi.mocked(getTaskResults).mockResolvedValue({
      task_id: "task_2",
      status: "completed",
      results: [
        {
          result_id: "res_001",
          node_id: "engine_1",
          node_type: "engine/ocr",
          status: "completed",
          file: {
            filename: "result.md",
            size_bytes: 12,
            content_type: "text/markdown",
            download_url: "/api/download"
          },
          metadata: {
            processing_time_ms: 120,
            page_count: 1,
            char_count: 12,
            word_count: 2
          },
          content: "hello result"
        }
      ]
    });
    const { result } = renderHook(() => useNodeLevelRun());

    await act(async () => {
      const success = await result.current.runNode("engine_1");
      expect(success).toBe(true);
    });

    expect(getTaskResults).toHaveBeenCalledWith("task_2");
    expect(useResultStore.getState().taskId).toBe("task_2");
    expect(useResultStore.getState().results).toHaveLength(1);
  });

  it("blocks node run when predecessor is not completed", async () => {
    // engine_1 has predecessor input_1 which is not marked as completed yet
    const { result } = renderHook(() => useNodeLevelRun());

    let success = true;
    await act(async () => {
      success = await result.current.runNode("engine_1");
    });

    expect(success).toBe(false);
    expect(message.warning).toHaveBeenCalledWith("The preceding nodes are not complete, so this node cannot run.");
    expect(createNodeRunTask).not.toHaveBeenCalled();
  });

  it("allows input node to run without predecessor check", async () => {
    vi.mocked(createNodeRunTask).mockResolvedValue({
      task_id: "task_input",
      status: "completed",
      node_id: "input_1",
      output_format: "markdown"
    });
    const { result } = renderHook(() => useNodeLevelRun());

    let success = false;
    await act(async () => {
      success = await result.current.runNode("input_1");
    });

    expect(success).toBe(true);
    expect(createNodeRunTask).toHaveBeenCalledTimes(1);
  });

  it("marks node run as failed when API call throws", async () => {
    vi.mocked(createNodeRunTask).mockRejectedValue(new Error("boom"));
    // Mark predecessor as completed so engine node can run
    useTaskExecutionStore.getState().updateNodeStatus("input_1", "completed");
    const { result } = renderHook(() => useNodeLevelRun());

    let success = true;
    await act(async () => {
      success = await result.current.runNode("engine_1");
    });

    expect(success).toBe(false);
    expect(useTaskExecutionStore.getState().taskStatus).toBe("failed");
    expect(useTaskExecutionStore.getState().nodeStatuses.engine_1).toBe("failed");
    expect(useTaskExecutionStore.getState().nodeErrors.engine_1).toContain("Node-level Run failed");
    expect(
      useTaskExecutionStore
        .getState()
        .eventLogs.some((entry) => entry.level === "error" && entry.message.includes("Node-level Run"))
    ).toBe(true);
    expect(message.error).toHaveBeenCalledWith("Node-level Run failed. Check the configuration or service status.");
  });
});
