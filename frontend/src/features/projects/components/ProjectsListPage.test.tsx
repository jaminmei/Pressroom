import "@testing-library/jest-dom/vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectsListPage from "@/features/projects/components/ProjectsListPage";
import { listProjects } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/services/projectApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/projectApi")>("@/services/projectApi");
  return { ...actual, listProjects: vi.fn() };
});

const project = (id: string, name: string) => ({
  id,
  name,
  documentCount: 0,
  lastUpdated: "2026-07-14T00:00:00Z",
  createdAt: "2026-07-14T00:00:00Z",
});

describe("ProjectsListPage", () => {
  beforeEach(() => {
    vi.mocked(listProjects).mockReset();
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: ["database.view", "database.create", "database.update", "database.delete"],
      },
      contextGeneration: 1,
      capabilities: ["database.view", "database.create", "database.update", "database.delete"],
    });
  });

  it("does not show a late project response after the workspace generation changes", async () => {
    let resolveOldRequest: ((value: Awaited<ReturnType<typeof listProjects>>) => void) | undefined;
    const oldRequest = new Promise<Awaited<ReturnType<typeof listProjects>>>((resolve) => {
      resolveOldRequest = resolve;
    });
    vi.mocked(listProjects)
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce([project("new-project", "New Workspace Database")]);

    render(
      <MemoryRouter initialEntries={["/database"]}>
        <ProjectsListPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(1));

    act(() => useWorkspaceStore.setState({ contextGeneration: 2 }));

    expect(await screen.findByText("New Workspace Database")).toBeInTheDocument();
    await act(async () => {
      resolveOldRequest?.([project("old-project", "Old Workspace Database")]);
      await oldRequest;
    });

    expect(screen.queryByText("Old Workspace Database")).not.toBeInTheDocument();
    expect(screen.getByText("New Workspace Database")).toBeInTheDocument();
  });
});
