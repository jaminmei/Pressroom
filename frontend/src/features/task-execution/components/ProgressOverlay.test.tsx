import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProgressOverlay from "@/features/task-execution/components/ProgressOverlay";
import { useTaskExecutionStore } from "@/features/task-execution/store";

describe("ProgressOverlay", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
  });

  it("renders running progress, timer and triggers cancel callback", () => {
    vi.useFakeTimers();
    const onCancel = vi.fn();
    const startedAt = new Date("2026-02-24T08:00:00Z").getTime();

    vi.setSystemTime(startedAt + 65_000);
    useTaskExecutionStore.setState({
      currentTaskId: "task_1",
      taskStatus: "running",
      executionStartedAt: startedAt,
      progress: {
        total_nodes: 5,
        completed_nodes: 2,
        failed_nodes: 0,
        pending_nodes: 3,
        current_node: "engine_1",
        percentage: 40
      }
    });

    render(<ProgressOverlay onCancel={onCancel} />);

    expect(screen.getByText("Task running")).toBeInTheDocument();
    expect(screen.getByText("2 / 5")).toBeInTheDocument();
    expect(screen.getByTestId("progress-elapsed")).toHaveTextContent("Elapsed: 01:05");
    fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
    expect(onCancel).toHaveBeenCalled();

    vi.useRealTimers();
  });

  it("returns null when task is idle", () => {
    render(<ProgressOverlay onCancel={vi.fn()} />);
    expect(screen.queryByText("Task running")).not.toBeInTheDocument();
  });
});
