import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WSConnectionBanner from "@/features/task-execution/components/WSConnectionBanner";
import { useTaskExecutionStore } from "@/features/task-execution/store";

describe("WSConnectionBanner", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
  });

  it("does not render when there is no active warning", () => {
    render(<WSConnectionBanner />);
    expect(screen.queryByTestId("ws-connection-banner")).not.toBeInTheDocument();
  });

  it("renders manual reconnect action and executes callback", async () => {
    const onManualReconnect = vi.fn().mockResolvedValue(true);

    useTaskExecutionStore.setState({
      taskStatus: "running",
      wsWarning: "連線中斷，無法自動恢復",
      manualReconnectAvailable: true
    });

    render(<WSConnectionBanner onManualReconnect={onManualReconnect} />);

    expect(screen.getByText("連線中斷，無法自動恢復")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reconnect manually" }));
      await Promise.resolve();
    });

    expect(onManualReconnect).toHaveBeenCalledTimes(1);
  });
});
