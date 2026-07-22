import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RunItem from "@/features/recent-runs/components/RunItem";

describe("RunItem", () => {
  it("renders task details and status", () => {
    render(
      <RunItem
        item={{
          task_id: "task_001",
          workflow_name: "PDF→OCR→MD",
          status: "completed",
          started_at: "2026-02-25T10:00:00Z"
        }}
        onClick={vi.fn()}
      />
    );

    expect(screen.getByText("001")).toBeInTheDocument();
    expect(screen.getByText("PDF→OCR→MD")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("calls onClick", () => {
    const onClick = vi.fn();
    render(
      <RunItem
        item={{
          task_id: "task_001",
          workflow_name: "PDF→OCR→MD",
          status: "completed",
          started_at: "2026-02-25T10:00:00Z"
        }}
        onClick={onClick}
      />
    );

    fireEvent.click(screen.getByTestId("run-item"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
