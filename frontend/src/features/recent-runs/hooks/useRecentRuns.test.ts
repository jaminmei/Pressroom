import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRecentRuns } from "@/features/recent-runs/hooks/useRecentRuns";
import { getTaskHistory } from "@/services/taskApi";

vi.mock("@/services/taskApi", () => ({
  getTaskHistory: vi.fn()
}));

describe("useRecentRuns", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("refreshes recent runs", async () => {
    vi.mocked(getTaskHistory).mockResolvedValue({
      items: [
        {
          task_id: "task_1",
          workflow_name: "PDF→OCR→MD",
          status: "completed",
          started_at: "2026-02-25T10:00:00Z"
        }
      ],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });

    const { result } = renderHook(() => useRecentRuns());

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.items).toHaveLength(1);
    expect(result.current.hasMore).toBe(false);
  });

  it("loads next page when has more", async () => {
    vi.mocked(getTaskHistory)
      .mockResolvedValueOnce({
        items: [
          {
            task_id: "task_1",
            workflow_name: "One",
            status: "completed",
            started_at: "2026-02-25T10:00:00Z"
          }
        ],
        meta: {
          total: 2,
          page: 1,
          limit: 1
        }
      })
      .mockResolvedValueOnce({
        items: [
          {
            task_id: "task_2",
            workflow_name: "Two",
            status: "failed",
            started_at: "2026-02-25T09:00:00Z"
          }
        ],
        meta: {
          total: 2,
          page: 2,
          limit: 1
        }
      });

    const { result } = renderHook(() => useRecentRuns({ pageSize: 1 }));

    await act(async () => {
      await result.current.refresh();
    });
    await act(async () => {
      await result.current.fetchMore();
    });

    expect(result.current.items.map((item) => item.task_id)).toEqual(["task_1", "task_2"]);
    expect(getTaskHistory).toHaveBeenNthCalledWith(2, { limit: 1, page: 2 });
  });

  it("captures error on request failure", async () => {
    vi.mocked(getTaskHistory).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useRecentRuns());

    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => {
      expect(result.current.error).toBe("network error");
      expect(result.current.items).toHaveLength(0);
    });
  });
});
