import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import { getTaskHistory, getTaskStatus } from "@/services/taskApi";

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
