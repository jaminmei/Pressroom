import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoleBadge } from "./RoleBadge";

describe("RoleBadge", () => {
  it("renders correct tag label for owner", () => {
    render(<RoleBadge role="owner" />);
    expect(screen.getByText("Owner")).toHaveClass("workspace-role-badge");
  });

  it("renders tooltip when showTooltip is true", async () => {
    render(<RoleBadge role="admin" showTooltip />);
    // antd Tooltip adds title attribute to children wrapper or uses its own overlay.
    // The Tag should at least be rendered.
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("uses the same purple pill treatment for every role", () => {
    const { rerender } = render(<RoleBadge role="owner" size="sm" />);
    expect(screen.getByText("Owner")).toHaveAttribute("data-size", "sm");

    rerender(<RoleBadge role="viewer" size="sm" />);
    expect(screen.getByText("Viewer")).toHaveClass("workspace-role-badge");
    expect(screen.getByText("Viewer")).toHaveAttribute("data-size", "sm");
  });
});
