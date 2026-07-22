import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectDetail } from "@/features/projects/hooks/useProjectDetail";
import { getProject, listRuns } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/services/projectApi", () => ({
  getProject: vi.fn(),
  listRuns: vi.fn(),
}));

const project = {
  id: "project-1",
  name: "Invoices",
  documentCount: 1,
  lastUpdated: "2026-07-21T00:00:00Z",
  createdAt: "2026-07-20T00:00:00Z",
};

describe("useProjectDetail permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getProject).mockResolvedValue(project);
    vi.mocked(listRuns).mockResolvedValue([]);
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view"],
      },
      capabilities: ["database.view"],
      contextGeneration: 1,
    });
  });

  it("loads the database without requesting run-only data", async () => {
    const { result } = renderHook(() => useProjectDetail("project-1"));

    await act(async () => Promise.resolve());

    expect(getProject).toHaveBeenCalledWith("project-1");
    expect(listRuns).not.toHaveBeenCalled();
    expect(result.current.project).toMatchObject(project);
    expect(result.current.error).toBeNull();
  });

  it("loads run summaries when run.view is available", async () => {
    useWorkspaceStore.setState({
      capabilities: ["database.view", "run.view"],
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view", "run.view"],
      },
    });

    renderHook(() => useProjectDetail("project-1"));
    await act(async () => Promise.resolve());

    expect(listRuns).toHaveBeenCalledWith("project-1");
  });

  it("masks cached run metadata on the first render after revocation", async () => {
    useWorkspaceStore.setState({
      capabilities: ["database.view", "run.view"],
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view", "run.view"],
      },
    });
    vi.mocked(listRuns).mockResolvedValue([
      {
        id: "run-secret",
        projectId: "project-1",
        workflowId: "workflow-1",
        workflowName: "Secret Workflow",
        name: "Secret Run",
        status: "completed",
        startedAt: "2026-07-21T00:00:00Z",
        completedAt: "2026-07-21T00:01:00Z",
        documentCount: 1,
        passRate: 100,
      },
    ]);
    const observedRunCounts: number[] = [];
    const { result } = renderHook(() => {
      const detail = useProjectDetail("project-1");
      observedRunCounts.push(detail.recentRuns.length);
      return detail;
    });
    await waitFor(() => expect(result.current.recentRuns).toHaveLength(1));
    const firstRevokedRender = observedRunCounts.length;
    vi.mocked(getProject).mockReturnValueOnce(
      new Promise<Awaited<ReturnType<typeof getProject>>>(() => undefined),
    );

    act(() => {
      useWorkspaceStore.setState({
        capabilities: ["database.view"],
        currentWorkspace: {
          id: "workspace-1",
          name: "Workspace",
          role: "viewer",
          isDefault: true,
          capabilities: ["database.view"],
        },
      });
    });

    expect(result.current.recentRuns).toEqual([]);
    expect(result.current.activity).toEqual([]);
    expect(observedRunCounts.slice(firstRevokedRender)).not.toContain(1);
  });
});
