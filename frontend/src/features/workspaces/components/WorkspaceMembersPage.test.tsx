import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";

import WorkspaceMembersPage from "./WorkspaceMembersPage";
import { usePermission } from "@/hooks/usePermission";
import { useWorkspaceMembers } from "../hooks/useWorkspaceMembers";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("antd", () => ({
  Alert: ({ message, description, action }: { message?: ReactNode; description?: ReactNode; action?: ReactNode }) => (
    <div role="alert">{message}{description}{action}</div>
  ),
  Button: ({ children, disabled, onClick }: { children?: ReactNode; disabled?: boolean; onClick?: () => void }) => (
    <button type="button" disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
  Input: ({ allowClear: _allowClear, prefix: _prefix, ...props }: Record<string, unknown>) => <input {...props} />,
  Empty: ({ description, ...props }: { description?: ReactNode; "data-testid"?: string }) => <div {...props}>{description}</div>,
  Select: (props: Record<string, unknown>) => <select {...props} />,
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children?: ReactNode }) => <>{children}</>,
  message: { error: vi.fn(), success: vi.fn() },
  Typography: { Text: ({ children }: { children?: ReactNode }) => <span>{children}</span> },
}));

vi.mock("@/components/Permissions/CapabilityMatrixDrawer", () => ({
  CapabilityMatrixDrawer: () => null,
}));

vi.mock("./WorkspaceMembersTable", () => ({
  WorkspaceMembersTable: ({ canChangeRole, canRemove }: { canChangeRole: boolean; canRemove: boolean }) => (
    <div data-testid="workspace-members-table">
      <button type="button" aria-label="Change Role" disabled={!canChangeRole} />
      <button type="button" aria-label="Remove" disabled={!canRemove} />
    </div>
  ),
}));

vi.mock("./AddWorkspaceMemberDialog", () => ({
  AddWorkspaceMemberDialog: ({ open }: { open: boolean }) => (
    <div data-testid="invite-dialog" data-open={open ? "true" : "false"} />
  ),
}));

vi.mock("./ChangeWorkspaceRoleDialog", () => ({
  ChangeWorkspaceRoleDialog: () => null,
}));

vi.mock("./RemoveWorkspaceMemberDialog", () => ({
  RemoveWorkspaceMemberDialog: () => null,
}));

vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: vi.fn(),
}));

vi.mock("../hooks/useWorkspaceMembers", () => ({
  useWorkspaceMembers: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: vi.fn(() => ({
    can: () => true,
    explain: () => ({ allowed: true, allowedRoles: [] }),
    role: "admin",
  })),
}));

describe("WorkspaceMembersPage", () => {
  const workspaceState = {
    currentWorkspace: {
      id: "ws-1",
      name: "Test Workspace",
      role: "admin" as const,
      isDefault: false,
      capabilities: [],
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "members.view", allowedRoles: [] }),
      role: "admin",
    });
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(workspaceState as never));
    vi.mocked(useWorkspaceMembers).mockReturnValue({
      members: [{ userId: "1", email: "test1@example.com", role: "admin", status: "active" }],
      total: 1,
      loading: false,
      error: null,
      inviteMember: vi.fn(),
      changeRole: vi.fn(),
      removeMember: vi.fn(),
      refresh: vi.fn(),
    });
  });

  const renderPage = (initialEntry = "/settings/workspace/members") => render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <WorkspaceMembersPage />
    </MemoryRouter>
  );

  it("renders table and invite button if allowed", () => {
    renderPage();

    expect(screen.getByTestId("workspace-members-table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /invite member/i })).toBeInTheDocument();
  });

  it("keeps the members table visible while loading", () => {
    vi.mocked(useWorkspaceMembers).mockReturnValue({
      members: [], total: 0, loading: true, error: null,
      inviteMember: vi.fn(), changeRole: vi.fn(), removeMember: vi.fn(), refresh: vi.fn(),
    });

    renderPage();
    expect(screen.getByTestId("workspace-members-table")).toBeInTheDocument();
    expect(screen.queryByTestId("workspace-members-empty")).not.toBeInTheDocument();
  });

  it("disables invite button if not allowed", () => {
    vi.mocked(usePermission).mockReturnValue({
      can: (cap) => !["members.invite"].includes(cap as string),
      explain: () => ({ allowed: false, capability: "members.invite", allowedRoles: [] }),
      role: "viewer",
    });

    renderPage();

    expect(screen.getByRole("button", { name: /invite member/i })).toBeDisabled();
  });

  it("renders a fetch error with a working retry button", () => {
    const refresh = vi.fn();
    vi.mocked(useWorkspaceMembers).mockReturnValue({
      members: [], total: 0, loading: false, error: "Members unavailable",
      inviteMember: vi.fn(), changeRole: vi.fn(), removeMember: vi.fn(), refresh,
    });

    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("Members unavailable");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("renders an explicit empty state", () => {
    vi.mocked(useWorkspaceMembers).mockReturnValue({
      members: [], total: 0, loading: false, error: null,
      inviteMember: vi.fn(), changeRole: vi.fn(), removeMember: vi.fn(), refresh: vi.fn(),
    });

    renderPage();
    expect(screen.getByTestId("workspace-members-empty")).toHaveTextContent(/no workspace members/i);
    expect(screen.queryByTestId("workspace-members-table")).not.toBeInTheDocument();
  });

  it("disables role changes when only member removal is allowed", () => {
    vi.mocked(usePermission).mockReturnValue({
      can: (capability) => capability === "members.remove",
      explain: () => ({ allowed: false, capability: "members.update_role", allowedRoles: [] }),
      role: "admin",
    });

    renderPage();
    expect(screen.getByRole("button", { name: /change role/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /remove/i })).toBeEnabled();
  });

  it("disables removal when only role changes are allowed", () => {
    vi.mocked(usePermission).mockReturnValue({
      can: (capability) => capability === "members.update_role",
      explain: () => ({ allowed: false, capability: "members.remove", allowedRoles: [] }),
      role: "admin",
    });

    renderPage();
    expect(screen.getByRole("button", { name: /change role/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /remove/i })).toBeDisabled();
  });

  it("opens the invite dialog from the action query and then cleans the URL", async () => {
    function LocationProbe() {
      const location = useLocation();
      return <output data-testid="location-search">{location.search}</output>;
    }

    render(
      <MemoryRouter initialEntries={["/settings/workspace/members?action=invite"]}>
        <WorkspaceMembersPage />
        <LocationProbe />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByTestId("invite-dialog")).toHaveAttribute("data-open", "true"));
    expect(screen.getByTestId("location-search")).toHaveTextContent("");
  });
});
