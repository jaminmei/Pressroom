import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import HistoryPanel from "@/features/workflow-editor/components/HistoryPanel";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { getTaskHistory, getTaskResults, getTaskStatus } from "@/services/taskApi";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import type { TaskHistoryItem } from "@/types/task";

vi.mock("@/services/taskApi", () => ({
  getTaskHistory: vi.fn(),
  getTaskStatus: vi.fn(),
  getTaskResults: vi.fn()
}));

const mockedGetTaskHistory = vi.mocked(getTaskHistory);
const mockedGetTaskStatus = vi.mocked(getTaskStatus);
const mockedGetTaskResults = vi.mocked(getTaskResults);

const baseHistoryItem: TaskHistoryItem = {
  task_id: "task_900",
  workflow_name: "Demo Workflow",
  status: "completed",
  started_at: "2026-03-03T10:00:00Z",
  completed_at: "2026-03-03T10:01:00Z",
  result_preview: "已產生預覽內容"
};

describe("HistoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useWorkflowPersistenceStore.getState().reset();
    useUIStore.setState({ ...initialUIState });

    mockedGetTaskHistory.mockResolvedValue({
      items: [{ ...baseHistoryItem }]
    });
    mockedGetTaskStatus.mockResolvedValue({
      task_id: "task_900",
      status: "completed",
      progress: {
        total_nodes: 1,
        completed_nodes: 1,
        failed_nodes: 0,
        pending_nodes: 0,
        current_node: "engine_ocr_1",
        percentage: 100
      },
      node_status: [
        {
          node_id: "engine_ocr_1",
          node_type: "engine/ocr",
          status: "completed",
          started_at: "2026-03-03T10:00:10Z",
          completed_at: "2026-03-03T10:00:50Z"
        }
      ]
    });
    mockedGetTaskResults.mockResolvedValue({
      task_id: "task_900",
      status: "completed",
      results: [
        {
          result_id: "result_1",
          node_id: "engine_ocr_1",
          node_type: "engine/ocr",
          status: "completed",
          file: {
            filename: "output.md",
            size_bytes: 12,
            content_type: "text/markdown",
            download_url: "/api/tasks/task_900/results/result_1/download"
          },
          metadata: {
            processing_time_ms: 1200,
            page_count: 1,
            char_count: 20,
            word_count: 5
          },
          content: "hello world"
        }
      ]
    });
  });

  it("hydrates compare context from review and switches to compare tab", async () => {
    render(<HistoryPanel />);

    expect(screen.getByText("Run History")).toBeInTheDocument();
    expect(await screen.findByText("Demo Workflow")).toBeInTheDocument();
    expect(mockedGetTaskHistory).toHaveBeenCalledWith({ limit: 20, page: 1 });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => {
      expect(mockedGetTaskStatus).toHaveBeenCalledWith("task_900");
      expect(mockedGetTaskResults).toHaveBeenCalledWith("task_900");
    });

    const taskState = useTaskExecutionStore.getState();
    expect(taskState.currentTaskId).toBe("task_900");
    expect(taskState.taskStatus).toBe("completed");
    expect(taskState.nodeStatuses.engine_ocr_1).toBe("completed");

    const resultState = useResultStore.getState();
    expect(resultState.taskId).toBe("task_900");
    expect(resultState.results).toHaveLength(1);
    expect(useUIStore.getState().rightPanelTab).toBe("compare");
  });

  it("renders history result_preview and truncates to 500 chars", async () => {
    const longPreview = "A".repeat(560);
    const truncatedPreview = `${"A".repeat(499)}…`;

    mockedGetTaskHistory.mockResolvedValueOnce({
      items: [{ ...baseHistoryItem, result_preview: longPreview }]
    });

    render(<HistoryPanel />);

    expect(await screen.findByText(truncatedPreview)).toBeInTheDocument();
    expect(truncatedPreview).toHaveLength(500);
  });

  it("renders graceful fallback when history result_preview is missing", async () => {
    mockedGetTaskHistory.mockResolvedValueOnce({
      items: [{ ...baseHistoryItem, result_preview: undefined }]
    });

    render(<HistoryPanel />);

    expect(await screen.findByText("No result preview")).toBeInTheDocument();
  });

  it("calls restore handler when clicking a version restore button", async () => {
    const onRestoreVersion = vi.fn().mockResolvedValue(true);
    useWorkflowPersistenceStore.getState().setVersions([
      { version: 2, status: "published", created_at: "2026-03-03T10:10:00Z" },
      { version: 1, status: "published", created_at: "2026-03-03T10:00:00Z" }
    ]);

    render(<HistoryPanel onRestoreVersion={onRestoreVersion} />);

    expect(await screen.findByText("Version History")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore v1" }));

    await waitFor(() => {
      expect(onRestoreVersion).toHaveBeenCalledWith(1);
    });
  });

  it("maps status badge colors by status in run history", async () => {
    mockedGetTaskHistory.mockResolvedValueOnce({
      items: [
        { ...baseHistoryItem, task_id: "task_completed", status: "completed" },
        { ...baseHistoryItem, task_id: "task_failed", status: "failed" },
        { ...baseHistoryItem, task_id: "task_running", status: "running", completed_at: undefined },
        { ...baseHistoryItem, task_id: "task_cancelled", status: "cancelled" }
      ]
    });

    render(<HistoryPanel />);

    expect(await screen.findByTestId("history-status-badge-completed")).toHaveClass(
      "history-panel-item-status--completed"
    );
    expect(screen.getByTestId("history-status-badge-failed")).toHaveClass(
      "history-panel-item-status--failed"
    );
    expect(screen.getByTestId("history-status-badge-running")).toHaveClass(
      "history-panel-item-status--running"
    );
    expect(screen.getByTestId("history-status-badge-cancelled")).toHaveClass(
      "history-panel-item-status--cancelled"
    );
  });
});
