import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import RecentRunsDrawer from "@/features/recent-runs/components/RecentRunsDrawer";

const useRecentRunsMock = vi.fn();

vi.mock("@/features/recent-runs/hooks/useRecentRuns", () => ({
  useRecentRuns: () => useRecentRunsMock()
}));

describe("RecentRunsDrawer", () => {
  it("renders run items", () => {
    useRecentRunsMock.mockReturnValue({
      items: [
        {
          task_id: "task_001",
          workflow_name: "PDF→OCR→MD",
          status: "completed",
          started_at: "2026-02-25T10:00:00Z"
        }
      ],
      loading: false,
      error: null,
      hasMore: false,
      fetchMore: vi.fn(),
      refresh: vi.fn()
    });

    render(
      <MemoryRouter>
        <RecentRunsDrawer onClose={vi.fn()} open />
      </MemoryRouter>
    );

    expect(screen.getByTestId("recent-runs-drawer")).toBeInTheDocument();
    expect(screen.getByText("PDF→OCR→MD")).toBeInTheDocument();
  });

  it("renders empty state", () => {
    useRecentRunsMock.mockReturnValue({
      items: [],
      loading: false,
      error: null,
      hasMore: false,
      fetchMore: vi.fn(),
      refresh: vi.fn()
    });

    render(
      <MemoryRouter>
        <RecentRunsDrawer onClose={vi.fn()} open />
      </MemoryRouter>
    );

    expect(screen.getByText("No run history yet")).toBeInTheDocument();
  });

  it("closes after clicking run item", () => {
    const onClose = vi.fn();
    useRecentRunsMock.mockReturnValue({
      items: [
        {
          task_id: "task_001",
          workflow_name: "PDF→OCR→MD",
          status: "completed",
          started_at: "2026-02-25T10:00:00Z"
        }
      ],
      loading: false,
      error: null,
      hasMore: false,
      fetchMore: vi.fn(),
      refresh: vi.fn()
    });

    render(
      <MemoryRouter>
        <RecentRunsDrawer onClose={onClose} open />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByTestId("run-item"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
