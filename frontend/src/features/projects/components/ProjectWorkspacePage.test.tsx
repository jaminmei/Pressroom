import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectWorkspacePage from "@/features/projects/components/ProjectWorkspacePage";
import { getRunResults, getRunStatus } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/features/projects/hooks/useProjectDetail", () => ({
  useProjectDetail: () => ({
    project: {
      id: "project-1",
      name: "Current Database",
      documentCount: 1,
      lastUpdated: "2026-07-14T00:00:00Z",
      createdAt: "2026-07-14T00:00:00Z",
      version: "1.0",
    },
    recentRuns: [],
    activity: [],
    loading: false,
    error: null,
  }),
}));

vi.mock("@/features/projects/components/DocumentsView", () => ({
  default: ({
    activeRunId,
    monitoredRunId,
    onViewFullRun,
    runResults,
  }: {
    activeRunId: string | null;
    monitoredRunId: string | null;
    onViewFullRun: (runId: string) => void;
    runResults: ReadonlyArray<{ documentName: string }>;
  }) => (
    <div>
      <div data-testid="active-run-id">{activeRunId}</div>
      <div data-testid="monitored-run-id">{monitoredRunId}</div>
      <div data-testid="run-results">{runResults.map((result) => result.documentName).join(",")}</div>
      <button onClick={() => onViewFullRun("run-from-document")}>View exact run</button>
    </div>
  ),
}));
vi.mock("@/features/projects/components/RunsView", () => ({
  default: ({
    onOpenRun,
    selectedRunId,
  }: {
    onOpenRun: (runId: string) => void;
    selectedRunId: string | null;
  }) => (
    <div>
      <div data-testid="selected-full-run">{selectedRunId}</div>
      <button onClick={() => onOpenRun("run-history")}>Open historical run</button>
    </div>
  ),
}));
vi.mock("@/features/projects/components/GroundTruthView", () => ({ default: () => null }));
vi.mock("@/features/projects/components/SettingsView", () => ({ default: () => null }));

vi.mock("@/services/projectApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/projectApi")>("@/services/projectApi");
  return { ...actual, getRunResults: vi.fn(), getRunStatus: vi.fn() };
});

describe("ProjectWorkspacePage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockReset();
    vi.mocked(getRunResults).mockReset();
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: ["database.view", "run.view"],
      },
      contextGeneration: 1,
      capabilities: ["database.view", "run.view"],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows clear empty states when the database has no runs", () => {
    render(
      <MemoryRouter initialEntries={["/database/project-1"]}>
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("overview-recent-runs-empty")).toHaveTextContent(
      "No runs yet. Upload documents and start a workflow to see runs here.",
    );
    expect(screen.getByTestId("overview-recent-activity-empty")).toHaveTextContent(
      "No activity yet. Completed and failed runs will appear here.",
    );
    expect(document.querySelector(".ant-skeleton")).not.toBeInTheDocument();
  });

  it("prevents an old active-run poll from updating the new workspace page", async () => {
    let resolveOldStatus: ((value: Awaited<ReturnType<typeof getRunStatus>>) => void) | undefined;
    const oldStatus = new Promise<Awaited<ReturnType<typeof getRunStatus>>>((resolve) => {
      resolveOldStatus = resolve;
    });
    vi.mocked(getRunStatus).mockReturnValue(oldStatus);
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-old",
        runId: "run-old",
        documentId: "document-old",
        documentName: "Old Workspace Document",
        status: "pass",
        executionStatus: "completed",
        hasGroundTruth: true,
        acceptedAsGT: false,
      },
    ]);

    render(
      <MemoryRouter
        initialEntries={[{ pathname: "/database/project-1", state: { activeRunId: "run-old" } }]}
      >
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(getRunStatus).toHaveBeenCalledWith("run-old");

    act(() => useWorkspaceStore.setState({ contextGeneration: 2 }));
    expect(screen.getByTestId("run-results")).toBeEmptyDOMElement();

    await act(async () => {
      resolveOldStatus?.({ status: "completed", completedCount: 1, totalDocuments: 1 });
      await oldStatus;
    });

    expect(getRunResults).not.toHaveBeenCalled();
    expect(screen.getByTestId("run-results")).toBeEmptyDOMElement();
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(getRunStatus).toHaveBeenCalledTimes(1);
  });

  it("opens the exact full run selected from a document history", () => {
    render(
      <MemoryRouter initialEntries={["/database/project-1"]}>
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("ws-nav-documents"));
    fireEvent.click(screen.getByRole("button", { name: "View exact run" }));

    expect(screen.getByTestId("selected-full-run")).toHaveTextContent(
      "run-from-document",
    );
  });

  it("opens the section requested through navigation state", () => {
    render(
      <MemoryRouter
        initialEntries={[{ pathname: "/database/project-1", state: { activeSection: "documents" } }]}
      >
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("ws-nav-documents")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("run-results")).toBeInTheDocument();
  });

  it("hides unauthorized sections and blocks direct run monitoring", async () => {
    useWorkspaceStore.setState({
      capabilities: ["database.view"],
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view"],
      },
    });

    render(
      <MemoryRouter
        initialEntries={[{ pathname: "/database/project-1", state: { activeRunId: "run-secret" } }]}
      >
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("ws-nav-runs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ws-nav-ground-truth")).not.toBeInTheDocument();
    expect(screen.getByTestId("project-section-forbidden")).toHaveTextContent(
      "You do not have permission to view this database section.",
    );
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(getRunStatus).not.toHaveBeenCalled();
    expect(getRunResults).not.toHaveBeenCalled();
  });

  it("does not render run-derived overview sections without run.view", () => {
    useWorkspaceStore.setState({
      capabilities: ["database.view"],
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view"],
      },
    });

    render(
      <MemoryRouter initialEntries={["/database/project-1"]}>
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByText("Recent Runs")).not.toBeInTheDocument();
    expect(screen.queryByText("Recent Activity")).not.toBeInTheDocument();
  });

  it("does not leak a historical run into Documents monitoring", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "completed",
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([]);

    render(
      <MemoryRouter initialEntries={["/database/project-1"]}>
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("ws-nav-runs"));
    fireEvent.click(screen.getByRole("button", { name: "Open historical run" }));
    await act(async () => vi.advanceTimersByTimeAsync(500));
    fireEvent.click(screen.getByTestId("ws-nav-documents"));

    expect(screen.getByTestId("active-run-id")).toHaveTextContent("run-history");
    expect(screen.getByTestId("monitored-run-id")).toBeEmptyDOMElement();
  });

  it("dismisses a completed Documents monitor after navigating away", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "completed",
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([]);

    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/database/project-1", state: { activeRunId: "run-new" } },
        ]}
      >
        <Routes>
          <Route path="/database/:projectId" element={<ProjectWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("monitored-run-id")).toHaveTextContent("run-new");
    await act(async () => vi.advanceTimersByTimeAsync(500));
    fireEvent.click(screen.getByTestId("ws-nav-overview"));
    fireEvent.click(screen.getByTestId("ws-nav-documents"));

    expect(screen.getByTestId("active-run-id")).toHaveTextContent("run-new");
    expect(screen.getByTestId("monitored-run-id")).toBeEmptyDOMElement();
  });
});
