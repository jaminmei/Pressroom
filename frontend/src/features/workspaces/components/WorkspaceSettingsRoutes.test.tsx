import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Outlet, createMemoryRouter, RouterProvider } from "react-router-dom";
import { Suspense } from "react";
import type { ReactNode, TextareaHTMLAttributes } from "react";
import { appRoutes } from "@/app/routes";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { usePermission } from "@/hooks/usePermission";

vi.mock("antd", () => ({
  Input: { TextArea: (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> },
  Card: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tabs: ({ items, activeKey }: { items?: Array<{ key: string; label: string }>; activeKey?: string }) => (
    <div>
      {items?.map((item) => (
        <span key={item.key} data-active={item.key === activeKey}>
          {item.label}
        </span>
      ))}
    </div>
  ),
  Typography: { Title: ({ children }: { children?: ReactNode }) => <h1>{children}</h1> },
}));

// Need to mock child components dependencies and components that might break in test env
vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/features/workspaces/hooks/useWorkspaceMembers", () => ({
  useWorkspaceMembers: () => ({
    members: [],
    loading: false,
    inviteMember: vi.fn(),
    changeRole: vi.fn(),
    removeMember: vi.fn(),
  }),
}));

vi.mock("@/features/workspaces/hooks/useWorkspaceAudit", () => ({
  useWorkspaceAudit: () => ({
    events: [],
    loading: false,
    error: null,
  }),
}));

vi.mock("@/features/auth/components/ProtectedRoute", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/Layout/AppLayout", () => {
  return {
    default: () => <Outlet />,
  };
});

vi.mock("@/features/workspaces/components/WorkspaceSettingsPage", () => ({
  default: () => <Outlet />,
}));

vi.mock("@/features/workspaces/components/WorkspaceOverviewPage", () => ({
  default: () => <div>Test Workspace</div>,
}));

vi.mock("@/features/workspaces/components/WorkspaceMembersPage", () => ({
  default: () => <div data-testid="workspace-members-table" />,
}));

vi.mock("@/features/workspaces/components/WorkspaceProvidersPage", () => ({
  default: () => <div>No providers configured for this workspace.</div>,
}));

vi.mock("@/features/workspaces/components/WorkspaceAuditPage", () => ({
  default: () => <div data-testid="workspace-audit-table" />,
}));

vi.mock("@/features/workspaces/components/WorkspaceGeneralPage", () => ({
  default: () => (
    <div>
      <div>General Details</div>
      <div>Danger Zone</div>
    </div>
  ),
}));

vi.mock("@/features/workflow-editor/components/WorkflowEditor", () => ({
  default: () => <div>Workflow Editor</div>,
}));

// Mock matchMedia for antd
window.matchMedia =
  window.matchMedia ||
  function () {
    return {
      matches: false,
      addListener: function () {},
      removeListener: function () {},
    };
  };

describe("WorkspaceSettingsRoutes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useWorkspaceStore).mockImplementation((selector) =>
      selector({
        currentWorkspace: {
          id: "ws-1",
          name: "Test Workspace",
          role: "admin",
          capabilities: [],
        },
        can: () => true,
        explain: () => ({ allowed: true, capability: "workspace.view", allowedRoles: [] }),
      } as never)
    );
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.view", allowedRoles: [] }),
      role: "admin",
    });
  });

  const renderRoute = (initialPath: string) => {
    const router = createMemoryRouter(appRoutes, {
      initialEntries: [initialPath],
    });

    render(
      <Suspense fallback={<div>Loading...</div>}>
        <RouterProvider router={router} />
      </Suspense>
    );
  };

  it("renders overview on /settings/workspace", async () => {
    renderRoute("/settings/workspace");
    await waitFor(() => {
      expect(screen.getByText("Test Workspace")).toBeInTheDocument();
    });
  });

  it("renders members on /settings/workspace/members", async () => {
    renderRoute("/settings/workspace/members");
    await waitFor(() => {
      expect(screen.getByTestId("workspace-members-table")).toBeInTheDocument();
    });
  });

  it("renders providers on /settings/workspace/providers", async () => {
    renderRoute("/settings/workspace/providers");
    await waitFor(() => {
      expect(screen.getByText("No providers configured for this workspace.")).toBeInTheDocument();
    });
  });

  it("renders audit on /settings/workspace/audit", async () => {
    renderRoute("/settings/workspace/audit");
    await waitFor(() => {
      expect(screen.getByTestId("workspace-audit-table")).toBeInTheDocument();
    });
  });

  it("renders general on /settings/workspace/general", async () => {
    renderRoute("/settings/workspace/general");
    await waitFor(() => {
      expect(screen.getByText("General Details")).toBeInTheDocument();
      expect(screen.getByText("Danger Zone")).toBeInTheDocument();
    });
  });
});
