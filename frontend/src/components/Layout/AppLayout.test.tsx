import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppLayout from "@/components/Layout/AppLayout";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { useAuthStore } from "@/stores/authStore";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

let outletMounts = 0;

function OutletContent() {
  useEffect(() => {
    outletMounts += 1;
  }, []);
  return <div data-testid="outlet-content">Outlet</div>;
}

function renderLayout(initialEntry = "/") {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppLayout />,
      children: [
        { index: true, element: <OutletContent /> },
        { path: "database", element: <div data-testid="outlet-content">Databases</div> },
        { path: "settings/workspace", element: <div data-testid="outlet-content">Workspace settings</div> },
        { path: "workflows/:workflowId", element: <div data-testid="outlet-content">Workflow editor</div> }
      ]
    }
  ], { initialEntries: [initialEntry] });

  return render(<RouterProvider router={router} />);
}

describe("AppLayout", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
    window.localStorage.clear();
    outletMounts = 0;
    useUIStore.setState(initialUIState);
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "user-1", email: "user@example.com" }
    });
    useWorkspaceStore.setState({
      status: "ready",
      currentWorkspace: null,
      memberships: [],
      capabilities: [
        "workflow.run",
        "workflow.edit_draft",
        "workflow.publish",
        "database.create"
      ],
      error: null,
      isSwitching: false,
      contextGeneration: 0
    });
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: null,
      nodeRegistry: { nodes: [], connection_rules: [] }
    });
  });

  it("renders header, sidebar and outlet", () => {
    renderLayout();

    expect(screen.getByTestId("app-header")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("outlet-content")).toBeInTheDocument();
  });

  it("remounts workspace surfaces when the context generation changes", async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: []
      },
      contextGeneration: 1
    });
    renderLayout();
    expect(outletMounts).toBe(1);

    act(() => useWorkspaceStore.setState({ contextGeneration: 2 }));

    await waitFor(() => expect(outletMounts).toBe(2));
  });

  it("namespaces recent workflows by user and workspace", async () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: []
      },
      contextGeneration: 1
    });
    renderLayout();

    act(() => {
      useWorkflowPersistenceStore.getState().setWorkflowMeta({ workflowId: "workflow-1" });
    });

    await waitFor(() => {
      expect(window.localStorage.getItem("dc.command-palette.recent-workflows:user-1:ws-1")).toContain("workflow-1");
    });
    expect(window.localStorage.getItem("dc.command-palette.recent-workflows")).toBeNull();
  });

  it("toggles sidebar with Ctrl/Cmd+B", () => {
    renderLayout();
    const initial = useUIStore.getState().sidebarCollapsed;

    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(useUIStore.getState().sidebarCollapsed).toBe(!initial);

    fireEvent.keyDown(window, { key: "b", metaKey: true });
    expect(useUIStore.getState().sidebarCollapsed).toBe(initial);
  });

  it("toggles command palette with Ctrl/Cmd+K", () => {
    renderLayout();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(useUIStore.getState().commandPaletteOpen).toBe(true);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(useUIStore.getState().commandPaletteOpen).toBe(false);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(useUIStore.getState().commandPaletteOpen).toBe(true);
  });

  it("does not show the desktop-only hint on responsive Database and Settings routes", () => {
    Object.defineProperty(window, "innerWidth", { value: 375, configurable: true });

    const database = renderLayout("/database");
    expect(screen.queryByText("Please use a desktop browser")).not.toBeInTheDocument();
    expect(screen.getByText("Databases")).toBeInTheDocument();
    database.unmount();

    renderLayout("/settings/workspace");
    expect(screen.queryByText("Please use a desktop browser")).not.toBeInTheDocument();
    expect(screen.getByText("Workspace settings")).toBeInTheDocument();
  });

  it("retains the desktop-only hint on mobile canvas editor routes", () => {
    Object.defineProperty(window, "innerWidth", { value: 375, configurable: true });

    renderLayout("/workflows/workflow-1");

    expect(screen.getByText("Please use a desktop browser")).toBeInTheDocument();
  });

  it("renders required commands when palette opens", () => {
    renderLayout();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    expect(screen.getByText("Go to Template Center")).toBeInTheDocument();
    expect(screen.getByText("Execute Workflow")).toBeInTheDocument();
    expect(screen.getByText("Save Draft")).toBeInTheDocument();
    expect(screen.getByText("Publish")).toBeInTheDocument();
    expect(screen.getByText("Clear Canvas")).toBeInTheDocument();
    expect(screen.getByText("Open Recent Runs")).toBeInTheDocument();
    expect(screen.getByText(/Apply:\s*PDF\s*→\s*OCR/)).toBeInTheDocument();
  });

  it("adds selected @node item to canvas center position", () => {
    vi.useFakeTimers();
    const rafSpy = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      });

    const shell = document.createElement("div");
    shell.className = "react-flow-shell";
    Object.defineProperty(shell, "clientWidth", { value: 800, configurable: true });
    Object.defineProperty(shell, "clientHeight", { value: 600, configurable: true });
    document.body.appendChild(shell);

    useWorkflowStore.setState({
      nodeRegistry: {
        nodes: [
          {
            node_type: "engine/ocr",
            display_name: "OCR Engine",
            category: "engine",
            description: "文本 OCR",
            keywords: ["ocr", "文本"],
            config_schema: { type: "object", properties: {} }
          }
        ],
        connection_rules: []
      }
    });

    renderLayout();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "@node ocr" } });

    act(() => {
      vi.advanceTimersByTime(220);
    });

    fireEvent.keyDown(screen.getByTestId("command-palette-input"), { key: "Enter" });

    act(() => {
      vi.advanceTimersByTime(30);
    });

    const createdNode = useWorkflowStore.getState().nodes[0];
    expect(useWorkflowStore.getState().nodes).toHaveLength(1);
    expect(createdNode?.type).toBe("engine/ocr");
    expect(createdNode?.position).toEqual({ x: 300, y: 260 });

    shell.remove();
    rafSpy.mockRestore();
    vi.useRealTimers();
  });
});
