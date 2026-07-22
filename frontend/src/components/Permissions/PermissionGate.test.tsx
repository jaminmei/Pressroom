import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PermissionGate } from "./PermissionGate";
import type { WorkspaceCapability, WorkspaceRole } from "@/types/workspace";

const mockCaps: WorkspaceCapability[] = [];
const mockRole: WorkspaceRole = "viewer";

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (cap: WorkspaceCapability) => mockCaps.includes(cap),
    explain: (cap: WorkspaceCapability) => ({ allowed: mockCaps.includes(cap), capability: cap, currentRole: mockRole, allowedRoles: [], reason: mockCaps.includes(cap) ? undefined : "Requires admin." }),
    role: mockRole
  })
}));

describe("PermissionGate", () => {
  it("renders children when allowed", () => {
    mockCaps.push("workspace.delete");
    render(
      <PermissionGate capability="workspace.delete">
        <div data-testid="child">Allowed!</div>
      </PermissionGate>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    mockCaps.pop();
  });

  it("renders null when denied and no fallback", () => {
    render(
      <PermissionGate capability="workspace.delete">
        <div data-testid="child">Allowed!</div>
      </PermissionGate>
    );
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("renders fallback when denied and fallback provided", () => {
    render(
      <PermissionGate capability="workspace.delete" fallback={<div data-testid="fallback">Denied!</div>}>
        <div data-testid="child">Allowed!</div>
      </PermissionGate>
    );
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });
});
