import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import RunPanel from "@/features/workflow-editor/components/RunPanel";

describe("RunPanel", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
  });

  it("shows empty states when no execution data", () => {
    render(<RunPanel />);

    expect(screen.getByText("Execution Monitor")).toBeInTheDocument();
    expect(screen.getByText("No execution records")).toBeInTheDocument();
    expect(screen.getByText("No events yet")).toBeInTheDocument();
  });

  it("renders node statuses and SSE log entries", () => {
    const store = useTaskExecutionStore.getState();
    store.setTaskId("task_101");
    store.setTaskStatus("running");
    store.updateNodeStatus("engine_ocr_1", "running");
    store.appendEventLog("節點 engine_ocr_1 開始執行。");
    store.appendEventLog("節點 engine_ocr_1 進度 50%。");

    render(<RunPanel />);

    expect(screen.getByText("engine_ocr_1")).toBeInTheDocument();
    expect(screen.getByText("節點 engine_ocr_1 開始執行。")).toBeInTheDocument();
    expect(screen.getByText("節點 engine_ocr_1 進度 50%。")).toBeInTheDocument();
  });
});
