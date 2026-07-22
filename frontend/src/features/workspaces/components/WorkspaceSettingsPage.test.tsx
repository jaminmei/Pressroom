import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useWorkspaceStore } from "@/stores/workspaceStore";
import WorkspaceSettingsPage from "./WorkspaceSettingsPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="settings-location">{location.pathname}</output>;
}

function renderSettings(initialEntry = "/settings/workspace") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/settings/workspace" element={<WorkspaceSettingsPage />}>
          <Route index element={<div>Overview content</div>} />
          <Route path="members" element={<div>Members content</div>} />
          <Route path="audit" element={<div>Audit content</div>} />
        </Route>
      </Routes>
      <LocationProbe />
    </MemoryRouter>
  );
}

describe("WorkspaceSettingsPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-1",
        name: "Legal Conversion Lab",
        isDefault: true,
        role: "admin",
        memberCount: 12,
        capabilities: ["workspace.view", "members.view", "provider.view", "audit.view"]
      },
      memberships: [],
      capabilities: ["workspace.view", "members.view", "provider.view", "audit.view"]
    });
  });

  it("renders the compact navigation with active state and member count", () => {
    renderSettings("/settings/workspace/members");

    expect(screen.getByRole("heading", { name: "Workspace Settings" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Workspace Settings" })).toBeInTheDocument();
    expect(screen.getByTestId("workspace-mobile-nav-members")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("workspace-mobile-nav-members")).toHaveTextContent("12");
    expect(screen.getByText("Members content")).toBeInTheDocument();
  });

  it("navigates with compact nav buttons", () => {
    renderSettings();
    fireEvent.click(screen.getByTestId("workspace-mobile-nav-members"));
    expect(screen.getByTestId("settings-location")).toHaveTextContent("/settings/workspace/members");
  });

  it("disables Audit and exposes the required role for viewers", () => {
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
    renderSettings();

    const audit = screen.getByTestId("workspace-mobile-nav-audit");
    expect(audit).toBeDisabled();
    expect(audit).toHaveAttribute("title", expect.stringContaining("Requires"));
  });
});
