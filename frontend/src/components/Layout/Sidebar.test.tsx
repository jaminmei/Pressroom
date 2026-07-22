import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Sidebar from "@/components/Layout/Sidebar";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

describe("Sidebar", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkspaceStore.setState({
      currentWorkspace: null,
      memberships: [],
      capabilities: []
    });
  });

  it("renders the doc annotation navigation item", () => {
    render(
      <MemoryRouter>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByTestId("sidebar-item-editor")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-item-studio")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-item-runs")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-item-templates")).toBeInTheDocument();
  });

  it("toggles collapsed state", () => {
    render(
      <MemoryRouter>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByTestId("sidebar-collapse-trigger"));

    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
  });

  it("opens recent runs callback", () => {
    const onOpenRecentRuns = vi.fn();
    render(
      <MemoryRouter>
        <Sidebar onOpenRecentRuns={onOpenRecentRuns} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByTestId("sidebar-item-runs"));

    expect(onOpenRecentRuns).toHaveBeenCalledTimes(1);
  });

  it("marks workflow studio as active on /studio", () => {
    render(
      <MemoryRouter initialEntries={["/studio"]}>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByTestId("sidebar-item-studio")).toHaveClass("is-active");
    expect(screen.getByTestId("sidebar-item-editor")).not.toHaveClass("is-active");
  });

  it("keeps workflow editor active for persisted workflow routes", () => {
    render(
      <MemoryRouter initialEntries={["/workflows/wf_123"]}>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByTestId("sidebar-item-editor")).toHaveClass("is-active");
    expect(screen.getByTestId("sidebar-item-studio")).not.toHaveClass("is-active");
  });

  it("renders workspace context navigation with member count", () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-1",
        name: "Legal Conversion Lab",
        isDefault: true,
        role: "admin",
        capabilities: ["workspace.view", "members.view", "provider.view", "audit.view"],
        memberCount: 12
      },
      capabilities: ["workspace.view", "members.view", "provider.view", "audit.view"]
    });

    render(
      <MemoryRouter initialEntries={["/settings/workspace/members"]}>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByText("Access, roles, providers, and audit")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-item-workspace-members")).toHaveClass("is-active");
    expect(screen.getByTestId("sidebar-item-workspace-members")).toHaveTextContent("12");
    expect(screen.getByTestId("sidebar-item-workspace-general")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar-item-editor")).not.toBeInTheDocument();
  });

  it("disables audit navigation with an explanatory reason", () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-1",
        name: "Viewer Workspace",
        isDefault: false,
        role: "viewer",
        capabilities: ["workspace.view", "members.view", "provider.view"]
      },
      capabilities: ["workspace.view", "members.view", "provider.view"]
    });

    render(
      <MemoryRouter initialEntries={["/settings/workspace"]}>
        <Sidebar onOpenRecentRuns={vi.fn()} />
      </MemoryRouter>
    );

    const auditItem = screen.getByTestId("sidebar-item-workspace-audit");
    expect(auditItem).toBeDisabled();
    expect(auditItem).toHaveAttribute("title", expect.stringContaining("Requires"));
  });
});
