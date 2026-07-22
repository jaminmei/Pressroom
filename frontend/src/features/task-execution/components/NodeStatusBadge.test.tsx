import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import NodeStatusBadge from "@/features/task-execution/components/NodeStatusBadge";

vi.mock("antd", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>
}));

describe("NodeStatusBadge", () => {
  it.each([
    "idle",
    "pending",
    "running",
    "completed",
    "failed",
    "awaiting_user_input",
    "skipped",
    "cancelled"
  ] as const)("renders %s status with SVG icon and data-testid", (status) => {
    const { container } = render(<NodeStatusBadge status={status} />);
    expect(screen.getByTestId(`node-status-${status}`)).toBeInTheDocument();
    expect(
      container.querySelector(`[data-testid="node-status-${status}"] svg`)
    ).toBeInTheDocument();
  });

  it("animates only the running status", () => {
    const { rerender } = render(<NodeStatusBadge status="pending" />);
    expect(screen.getByTestId("node-status-pending")).not.toHaveClass("node-status-animated");

    rerender(<NodeStatusBadge status="running" />);
    expect(screen.getByTestId("node-status-running")).toHaveClass("node-status-animated");

    rerender(<NodeStatusBadge status="completed" />);
    expect(screen.getByTestId("node-status-completed")).not.toHaveClass("node-status-animated");
  });

  it("keeps the badge compact while exposing a readable running label", () => {
    render(<NodeStatusBadge status="running" />);

    expect(screen.getByLabelText("Node status: Running")).toBeInTheDocument();
    expect(screen.queryByText("Running")).not.toBeInTheDocument();
  });

  it("renders a dedicated check mark for completed nodes", () => {
    const { container } = render(<NodeStatusBadge status="completed" />);

    expect(screen.getByLabelText("Node status: Completed")).toBeInTheDocument();
    expect(container.querySelector(".node-status-check")).toBeInTheDocument();
  });
});
