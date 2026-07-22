import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import { getTaskHistory, getTaskStatus, submitBlockSelection } from "@/services/taskApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn()
  }
}));

describe("taskApi", () => {
  it("loads task status from /tasks/{id}", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        task_id: "task_1",
        status: "running"
      }
    } as never);

    const response = await getTaskStatus("task_1");

    expect(apiClient.get).toHaveBeenCalledWith("/tasks/task_1");
    expect(response.status).toBe("running");
  });

  it("submits block selection input", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        task_id: "task_1",
        node_id: "block_selector_1",
        status: "running"
      }
    } as never);

    await submitBlockSelection("task_1", "block_selector_1", {
      input_type: "block_selection",
      payload: {
        source_image_id: "img_001",
        selected_blocks: []
      }
    });

    expect(apiClient.post).toHaveBeenCalledWith("/tasks/task_1/nodes/block_selector_1/input", {
      input_type: "block_selection",
      payload: {
        source_image_id: "img_001",
        selected_blocks: []
      }
    });
  });

  it("loads recent task history with query params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        success: true,
        data: [
          {
            task_id: "task_1",
            workflow_name: "PDF→OCR→MD",
            status: "completed",
            started_at: "2026-02-25T10:00:00Z"
          }
        ],
        meta: { total: 1, page: 1, limit: 20 }
      }
    } as never);

    const response = await getTaskHistory({ limit: 20, page: 1 });

    expect(apiClient.get).toHaveBeenCalledWith("/tasks/history", {
      params: { limit: 20, page: 1 }
    });
    expect(response.items).toHaveLength(1);
    expect(response.meta?.total).toBe(1);
  });
});
