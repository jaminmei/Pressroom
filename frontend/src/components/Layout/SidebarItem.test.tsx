import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SidebarItem from "@/components/Layout/SidebarItem";

describe("SidebarItem", () => {
  it("renders icon and label when expanded", () => {
    render(
      <SidebarItem
        active
        collapsed={false}
        dataTestId="sidebar-item-editor"
        icon={<span data-testid="icon">I</span>}
        label="Workflow Editor"
        onClick={vi.fn()}
      />
    );

    expect(screen.getByTestId("icon")).toBeInTheDocument();
    expect(screen.getByText("Workflow Editor")).toBeInTheDocument();
  });

  it("renders icon only when collapsed", () => {
    render(
      <SidebarItem
        active={false}
        collapsed
        dataTestId="sidebar-item-editor"
        icon={<span data-testid="icon">I</span>}
        label="Workflow Editor"
        onClick={vi.fn()}
      />
    );

    expect(screen.getByTestId("icon")).toBeInTheDocument();
    expect(screen.queryByText("Workflow Editor")).not.toBeInTheDocument();
  });

  it("invokes onClick", () => {
    const onClick = vi.fn();
    render(
      <SidebarItem
        active={false}
        collapsed={false}
        dataTestId="sidebar-item-editor"
        icon={<span>I</span>}
        label="Workflow Editor"
        onClick={onClick}
      />
    );

    fireEvent.click(screen.getByTestId("sidebar-item-editor"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("exposes a disabled reason and blocks unavailable items", () => {
    const onClick = vi.fn();
    render(
      <SidebarItem
        active={false}
        collapsed={false}
        dataTestId="sidebar-item-audit"
        disabled
        disabledReason="Requires owner or admin."
        icon={<span>A</span>}
        label="Audit"
        onClick={onClick}
      />
    );

    const item = screen.getByTestId("sidebar-item-audit");
    expect(item).toBeDisabled();
    expect(item).toHaveAttribute("title", "Audit: Requires owner or admin.");
    fireEvent.click(item);
    expect(onClick).not.toHaveBeenCalled();
  });
});
