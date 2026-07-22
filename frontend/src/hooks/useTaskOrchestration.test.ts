import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useTaskOrchestration } from "@/hooks/useTaskOrchestration";
import { getTaskResults, submitBlockSelection } from "@/services/taskApi";
import { cancelWorkflowTask, createWorkflowTask } from "@/services/workflowApi";
import type { TaskStatus } from "@/types/task";
import { useWorkspaceStore } from "@/stores/workspaceStore";

let capturedOnTaskFinished: ((taskId: string, status: TaskStatus) => void) | undefined;

vi.mock("@/features/task-execution/hooks/useWebSocket", () => ({
  useWebSocket: (options: { onTaskFinished?: (taskId: string, status: TaskStatus) => void }) => {
    capturedOnTaskFinished = options.onTaskFinished;
    return { isConnected: true, manualReconnect: vi.fn().mockResolvedValue(true), sendCommand: vi.fn() };
  }
}));

vi.mock("@/services/workflowApi", () => ({
  buildWorkflowTaskFormData: vi.fn((workflow: unknown, files: File[]) => {
    const formData = new FormData();
    formData.append("workflow", JSON.stringify(workflow));
    files.forEach((file) => formData.append("files", file));
    return formData;
  }),
  createWorkflowTask: vi.fn(),
  cancelWorkflowTask: vi.fn()
}));

vi.mock("@/services/taskApi", () => ({
  getTaskResults: vi.fn(),
  getTaskStatus: vi.fn().mockResolvedValue({ node_status: [] }),
  submitBlockSelection: vi.fn()
}));

describe("useTaskOrchestration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedOnTaskFinished = undefined;
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          data: {
            label: "PDF 輸入",
            config: {},
            configSchema: {
              type: "object",
              properties: {
                file: { type: "file" }
              },
              required: ["file"]
            }
          }
        },
        {
          id: "engine_1",
          type: "engine/ocr",
          data: {
            label: "OCR",
            config: {},
            configSchema: {
              type: "object",
              properties: {
                model: { type: "string" }
              },
              required: ["model"]
            }
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
            }
          }
        },
        {
          id: "end_1",
          type: "end/final",
          data: {
            label: "End",
            config: {},
            configSchema: {
              type: "object",
              properties: {}
            }
          }
        }
      ],
      edges: [
        { id: "e1", source: "input_1", target: "engine_1" },
        { id: "e2", source: "engine_1", target: "output_1" },
        { id: "e3", source: "output_1", target: "end_1" }
      ],
      nodeConfigs: {
        input_1: {},
        engine_1: { model: "paddleocr", provider_id: "provider_1" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: {
        input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" })
      },
      nodeRegistry: {
        nodes: [
          {
            node_type: "input/pdf",
            display_name: "PDF 輸入",
            category: "input",
            config_schema: {
              type: "object",
              properties: {
                file: { type: "file" }
              },
              required: ["file"]
            },
            output_types: ["application/pdf"],
            max_inputs: 0,
            max_outputs: -1
          },
          {
            node_type: "engine/ocr",
            display_name: "OCR",
            category: "engine",
            config_schema: {
              type: "object",
              properties: {
                model: { type: "string" }
              },
              required: ["model"]
            },
            input_types: ["application/pdf"],
            output_types: ["text/raw"],
            max_inputs: 1,
            max_outputs: -1
          },
          {
            node_type: "output/markdown",
            display_name: "Markdown",
            category: "output",
            config_schema: {
              type: "object",
              properties: {}
            },
            input_types: ["text/raw"],
            output_types: [],
            max_inputs: 1,
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
            output_types: [],
            max_inputs: -1,
            max_outputs: 0
          }
        ],
        connection_rules: [
          { from_category: "input", to_categories: ["engine", "output"] },
          { from_category: "engine", to_categories: ["output"] },
          { from_category: "output", to_categories: ["end"] }
        ]
      },
      selectedNodeId: null
    });
  });

  it("validates and submits workflow task", async () => {
    vi.mocked(createWorkflowTask).mockResolvedValue({
      task_id: "task_1",
      status: "pending"
    });
    const { result } = renderHook(() => useTaskOrchestration());

    let execution:
      | {
          ok: boolean;
          taskId?: string;
          errors: Array<{ code: string }>;
        }
      | undefined;
    await act(async () => {
      execution = await result.current.executeWorkflow();
    });

    expect(execution?.ok).toBe(true);
    expect(createWorkflowTask).toHaveBeenCalledTimes(1);
    expect(useTaskExecutionStore.getState().currentTaskId).toBe("task_1");
    expect(useTaskExecutionStore.getState().taskStatus).toBe("pending");
  });

  it("loads a direct terminal response and releases the active operation", async () => {
    vi.mocked(createWorkflowTask).mockResolvedValue({
      task_id: "task_terminal",
      status: "completed"
    });
    vi.mocked(getTaskResults).mockResolvedValue({
      task_id: "task_terminal",
      status: "completed",
      results: []
    });
    const { result } = renderHook(() => useTaskOrchestration());

    await act(async () => {
      await result.current.executeWorkflow();
    });

    expect(getTaskResults).toHaveBeenCalledWith("task_terminal");
    expect(useTaskExecutionStore.getState().activeOperationId).toBeNull();
    expect(useResultStore.getState().taskId).toBe("task_terminal");
  });

  it("drops a late create response after an A-B-A context change", async () => {
    let resolveTask!: (value: { task_id: string; status: "pending" }) => void;
    vi.mocked(createWorkflowTask).mockReturnValueOnce(
      new Promise((resolve) => { resolveTask = resolve; })
    );
    useWorkspaceStore.setState({
      currentWorkspace: { id: "workspace-a", name: "A", isDefault: false, role: "admin", capabilities: [] },
      contextGeneration: 100
    });
    const { result } = renderHook(() => useTaskOrchestration());

    let executionPromise!: ReturnType<typeof result.current.executeWorkflow>;
    act(() => {
      executionPromise = result.current.executeWorkflow();
    });
    act(() => {
      useTaskExecutionStore.getState().reset();
      useWorkspaceStore.setState({
        currentWorkspace: { id: "workspace-b", name: "B", isDefault: false, role: "admin", capabilities: [] },
        contextGeneration: 101
      });
      useWorkspaceStore.setState({
        currentWorkspace: { id: "workspace-a", name: "A", isDefault: false, role: "admin", capabilities: [] },
        contextGeneration: 102
      });
      resolveTask({ task_id: "task_stale", status: "pending" });
    });

    let execution!: Awaited<typeof executionPromise>;
    await act(async () => {
      execution = await executionPromise;
    });
    expect(execution).toMatchObject({ ok: false, errors: [{ code: "workspace_context_changed" }] });
    expect(useTaskExecutionStore.getState().currentTaskId).toBeNull();
    expect(useTaskExecutionStore.getState().taskStatus).toBe("idle");
  });

  it("returns validation errors without calling API", async () => {
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {}
    });
    const { result } = renderHook(() => useTaskOrchestration());

    let execution:
      | {
          ok: boolean;
          taskId?: string;
          errors: Array<{ code: string }>;
        }
      | undefined;
    await act(async () => {
      execution = await result.current.executeWorkflow();
    });

    expect(execution?.ok).toBe(false);
    expect(createWorkflowTask).not.toHaveBeenCalled();
    expect((execution?.errors ?? []).length).toBeGreaterThan(0);
  });

  it("returns backend error details when task creation fails with 400", async () => {
    vi.mocked(createWorkflowTask).mockRejectedValue({
      response: {
        status: 400,
        data: {
          error: {
            code: "workflow_invalid",
            message: "OCR engine is unavailable",
            details: {
              node_id: "engine_1"
            }
          }
        }
      }
    });
    const { result } = renderHook(() => useTaskOrchestration());

    let execution:
      | {
          ok: boolean;
          taskId?: string;
          errors: Array<{ code: string; message: string; nodeId?: string }>;
          errorMessage?: string;
          errorNodeId?: string;
        }
      | undefined;
    await act(async () => {
      execution = await result.current.executeWorkflow();
    });

    expect(execution?.ok).toBe(false);
    expect(execution?.errors).toEqual([
      {
        code: "backend_validation",
        message: "OCR engine is unavailable",
        nodeId: "engine_1"
      }
    ]);
    expect(execution?.errorMessage).toBe("OCR engine is unavailable");
    expect(execution?.errorNodeId).toBe("engine_1");
    expect(useTaskExecutionStore.getState().taskStatus).toBe("failed");
  });

  it("loads results when SSE notifies task completed", async () => {
    vi.mocked(createWorkflowTask).mockResolvedValue({
      task_id: "task_2",
      status: "pending"
    });
    vi.mocked(getTaskResults).mockResolvedValue({
      task_id: "task_2",
      status: "completed",
      results: []
    });
    const { result } = renderHook(() => useTaskOrchestration());

    await act(async () => {
      await result.current.executeWorkflow();
    });
    act(() => {
      capturedOnTaskFinished?.("task_2", "completed");
    });

    await waitFor(() => {
      expect(useResultStore.getState().taskId).toBe("task_2");
    });
  });

  it("cancels running task", async () => {
    useTaskExecutionStore.setState({
      currentTaskId: "task_3",
      taskStatus: "running"
    });
    const { result } = renderHook(() => useTaskOrchestration());

    await act(async () => {
      await result.current.cancelTask();
    });

    expect(cancelWorkflowTask).toHaveBeenCalledWith("task_3");
  });

  it("submits block selection input and clears pending request", async () => {
    useTaskExecutionStore.setState({
      currentTaskId: "task_4",
      taskStatus: "running",
      blockSelectionRequest: {
        node_id: "block_selector_1",
        node_type: "processor/block_selector",
        input_type: "block_selection",
        payload: {
          source_image: {
            image_id: "img_001",
            page_number: 1,
            width: 1280,
            height: 720,
            preview_url: "/preview"
          },
          blocks: []
        }
      }
    });

    vi.mocked(submitBlockSelection).mockResolvedValue({
      task_id: "task_4",
      node_id: "block_selector_1",
      status: "running"
    });

    const { result } = renderHook(() => useTaskOrchestration());

    await act(async () => {
      await result.current.submitNodeInputSelection("block_selector_1", {
        input_type: "block_selection",
        payload: {
          source_image_id: "img_001",
          selected_blocks: []
        }
      });
    });

    expect(submitBlockSelection).toHaveBeenCalledWith("task_4", "block_selector_1", {
      input_type: "block_selection",
      payload: {
        source_image_id: "img_001",
        selected_blocks: []
      }
    });
    expect(useTaskExecutionStore.getState().blockSelectionRequest).toBeNull();
    expect(useTaskExecutionStore.getState().nodeStatuses.block_selector_1).toBe("running");
  });
});
