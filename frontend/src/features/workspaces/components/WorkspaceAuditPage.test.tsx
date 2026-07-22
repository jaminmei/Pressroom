import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import WorkspaceAuditPage from "./WorkspaceAuditPage";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useWorkspaceAudit } from "../hooks/useWorkspaceAudit";
import { usePermission } from "@/hooks/usePermission";

vi.mock("antd", () => ({
  Alert: ({ message, description, action, ...props }: { message?: ReactNode; description?: ReactNode; action?: ReactNode }) => (
    <div role="alert" {...props}>{message}{description}{action}</div>
  ),
  Button: ({ children, ...props }: { children?: ReactNode }) => <button type="button" {...props}>{children}</button>,
  Result: ({ title, subTitle, ...props }: { title?: ReactNode; subTitle?: ReactNode; "data-testid"?: string }) => (
    <div {...props}>
      <div>{title}</div>
      <div>{subTitle}</div>
    </div>
  ),
}));

vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: vi.fn(() => ({
    can: () => true,
    explain: () => ({ allowed: true, allowedRoles: [] }),
    role: "admin",
  })),
}));

vi.mock("../hooks/useWorkspaceAudit", () => ({
  useWorkspaceAudit: vi.fn(),
}));

describe("WorkspaceAuditPage", () => {
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
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(workspaceState as never));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "audit.view", allowedRoles: [] }),
      role: "admin",
    });
  });

  it("discloses that audit events are not persisted", () => {
    vi.mocked(useWorkspaceAudit).mockReturnValue({
      events: [
        {
          id: "1",
          type: "workspace.created",
          message: "Workspace created",
          createdAt: "2026-07-09T10:00:00Z",
        },
      ],
      total: 1,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<WorkspaceAuditPage />);
    expect(screen.getByTestId("audit-coming-soon-banner")).toHaveTextContent(/not persisted/i);
  });

  it("keeps the non-persistence notice visible while loading", () => {
    vi.mocked(useWorkspaceAudit).mockReturnValue({
      events: [], total: 0, loading: true, error: null, refresh: vi.fn(),
    });

    render(<WorkspaceAuditPage />);
    expect(screen.getByTestId("audit-coming-soon-banner")).toBeInTheDocument();
  });

  it("does not present an empty response as audit evidence", () => {
    vi.mocked(useWorkspaceAudit).mockReturnValue({
      events: [],
      total: 0,
      loading: false,
      error: "Something went wrong",
      refresh: vi.fn(),
    });

    render(<WorkspaceAuditPage />);
    expect(screen.getByTestId("audit-coming-soon-banner")).toHaveTextContent(/not persisted/i);
    expect(screen.queryByText(/no audit events yet/i)).not.toBeInTheDocument();
  });

  it("renders a 403 state and disables the audit hook when access is denied", () => {
    vi.mocked(usePermission).mockReturnValue({
      can: () => false,
      explain: () => ({ allowed: false, capability: "audit.view", allowedRoles: [] }),
      role: "viewer",
    });
    vi.mocked(useWorkspaceAudit).mockReturnValue({
      events: [], total: 0, loading: false, error: null, refresh: vi.fn(),
    });

    render(<WorkspaceAuditPage />);
    expect(useWorkspaceAudit).toHaveBeenCalledWith("ws-1", false);
    expect(screen.getByTestId("workspace-audit-denied")).toHaveTextContent(/access denied/i);
    expect(screen.queryByTestId("workspace-audit-table")).not.toBeInTheDocument();
  });

  it("does not render an empty-state claim", () => {
    vi.mocked(useWorkspaceAudit).mockReturnValue({
      events: [], total: 0, loading: false, error: null, refresh: vi.fn(),
    });

    render(<WorkspaceAuditPage />);
    expect(screen.getByTestId("audit-coming-soon-banner")).toHaveTextContent(/events are not persisted/i);
  });
});
