import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskPolling } from "@/hooks/useTaskPolling";
import { getTaskStatus } from "@/services/taskApi";

vi.mock("@/services/taskApi", () => ({
  getTaskStatus: vi.fn()
}));

const mockedGetTaskStatus = vi.mocked(getTaskStatus);

describe("useTaskPolling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("polls task status and stops when task completes", async () => {
    vi.useFakeTimers();

    mockedGetTaskStatus
      .mockResolvedValueOnce({
        task_id: "task_1",
        status: "running"
      })
      .mockResolvedValueOnce({
        task_id: "task_1",
        status: "completed"
      });

    const onFinished = vi.fn();

    const { result } = renderHook(() =>
      useTaskPolling({
        taskId: "task_1",
        enabled: true,
        intervalMs: 2000,
        onFinished
      })
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(mockedGetTaskStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(onFinished).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });

    expect(mockedGetTaskStatus).toHaveBeenCalledTimes(2);
    expect(result.current.status?.status).toBe("completed");
    expect(result.current.isPolling).toBe(false);
  });
});
