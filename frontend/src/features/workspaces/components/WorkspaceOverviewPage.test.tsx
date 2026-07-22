import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import WorkspaceOverviewPage from "./WorkspaceOverviewPage";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { WorkspaceState } from "@/stores/workspaceStore";

vi.mock("antd", () => ({
  Card: ({ children, title }: { children?: ReactNode; title?: ReactNode }) => (
    <section>
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  ),
  Col: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Row: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Typography: {
    Paragraph: ({ children }: { children?: ReactNode }) => <p>{children}</p>,
    Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
    Title: ({ children }: { children?: ReactNode }) => <h1>{children}</h1>,
  },
}));

vi.mock("@/components/Permissions/RoleBadge", () => ({
  RoleBadge: ({ role }: { role: string }) => <span>{role === "admin" ? "Admin" : role}</span>,
}));

vi.mock("@/components/Permissions/PermissionButton", () => ({
  PermissionButton: ({ children, capability: _capability, icon: _icon, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { capability?: string; icon?: ReactNode }) => (
    <button type="button" {...props}>{children}</button>
  ),
}));

vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (_cap: string) => true,
    explain: () => ({}),
    role: "admin",
  }),
}));

describe("WorkspaceOverviewPage", () => {
  const mockWorkspaceState = {
    currentWorkspace: {
      id: "ws-1",
      name: "Test Workspace",
      isDefault: true,
      role: "admin",
      capabilities: [],
      memberCount: 5,
      workflowCount: 2,
    },
  } as unknown as WorkspaceState;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders workspace name and role badge", () => {
    vi.mocked(useWorkspaceStore).mockImplementation((selector) =>
      selector(mockWorkspaceState)
    );

    render(
      <MemoryRouter>
        <WorkspaceOverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByText("Test Workspace")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument(); // role badge
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/Your Role:/)).toHaveTextContent("Admin access");
    expect(screen.queryByText("Default workspace")).not.toBeInTheDocument();
  });

  it("renders nothing if currentWorkspace is null", () => {
    vi.mocked(useWorkspaceStore).mockImplementation(() => null);
    const { container } = render(
      <MemoryRouter>
        <WorkspaceOverviewPage />
      </MemoryRouter>
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders unknown metrics as em dashes and wires quick action routes", () => {
    vi.mocked(useWorkspaceStore).mockImplementation((selector) =>
      selector({
        currentWorkspace: {
          id: "ws-1",
          name: "Test Workspace",
          isDefault: false,
          role: "admin",
          capabilities: [],
        },
      } as never)
    );

    function LocationProbe() {
      return <output data-testid="location">{useLocation().pathname}{useLocation().search}</output>;
    }

    render(
      <MemoryRouter initialEntries={["/settings/workspace"]}>
        <WorkspaceOverviewPage />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(screen.getAllByText("—")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Invite member" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/settings/workspace/members?action=invite");
  });
});
