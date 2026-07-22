import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { PermissionButton } from "./PermissionButton";
import type { WorkspaceCapability, WorkspaceRole } from "@/types/workspace";

let mockCaps: WorkspaceCapability[] = [];
let mockRole: WorkspaceRole = "viewer";

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (cap: WorkspaceCapability) => mockCaps.includes(cap),
    explain: (cap: WorkspaceCapability) => ({ allowed: mockCaps.includes(cap), capability: cap, currentRole: mockRole, allowedRoles: [], reason: mockCaps.includes(cap) ? undefined : "Requires admin." }),
    role: mockRole
  })
}));

describe("PermissionButton", () => {
  beforeEach(() => {
    mockCaps = [];
    mockRole = "viewer";
  });

  it("is enabled and clickable when allowed", () => {
    mockCaps = ["workspace.delete"];
    const onClick = vi.fn();
    render(<PermissionButton capability="workspace.delete" onClick={onClick}>Delete</PermissionButton>);

    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn).not.toBeDisabled();

    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is disabled and shows tooltip when denied", async () => {
    mockCaps = [];
    const onClick = vi.fn();
    render(<PermissionButton capability="workspace.delete" onClick={onClick}>Delete</PermissionButton>);

    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn).toBeDisabled();

    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();

    const wrapper = btn.parentElement!;
    expect(wrapper).toHaveAttribute("tabindex", "0");
    expect(wrapper).toHaveAttribute("aria-disabled", "true");
    expect(btn).toHaveAttribute("aria-describedby");
    expect(screen.getByText("Requires admin.")).toBeInTheDocument();
  });

  it("blocks Enter and Space activation without trapping Tab navigation", () => {
    const onClick = vi.fn();
    render(<PermissionButton capability="workspace.delete" onClick={onClick}>Delete</PermissionButton>);
    const wrapper = screen.getByRole("button", { name: "Delete" }).parentElement!;

    expect(fireEvent.keyDown(wrapper, { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(wrapper, { key: " " })).toBe(false);
    expect(fireEvent.keyDown(wrapper, { key: "Tab" })).toBe(true);
    fireEvent.click(wrapper);

    expect(onClick).not.toHaveBeenCalled();
  });

  it("is disabled and shows inline reason when denied and placement is inline", () => {
    mockCaps = [];
    render(
      <PermissionButton capability="workspace.delete" disabledReasonPlacement="inline">
        Delete
      </PermissionButton>
    );

    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn).toBeDisabled();

    expect(screen.getAllByText("Requires admin.")).toHaveLength(2);
  });
});
