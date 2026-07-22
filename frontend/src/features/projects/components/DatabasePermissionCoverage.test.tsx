import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GroundTruthView from "@/features/projects/components/GroundTruthView";
import SettingsView from "@/features/projects/components/SettingsView";
import { useActiveRun } from "@/features/projects/hooks/useActiveRun";
import {
  acceptAsGT,
  getRunResults,
  getRunStatus,
  listDocuments,
  updateDatabaseSettings,
} from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/services/projectApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/projectApi")>("@/services/projectApi");
  return {
    ...actual,
    acceptAsGT: vi.fn(),
    getRunResults: vi.fn(),
    getRunStatus: vi.fn(),
    listDocuments: vi.fn(),
    updateDatabaseSettings: vi.fn(),
  };
});

function ActiveRunHarness() {
  const run = useActiveRun("project-1");
  return (
    <div>
      <button onClick={() => run.startMonitoring("run-1")} type="button">Monitor</button>
      <button onClick={() => run.acceptAsGT("doc-1")} type="button">Accept</button>
      <span data-testid="accepted">{String(run.results[0]?.acceptedAsGT ?? false)}</span>
    </div>
  );
}

describe("database permission coverage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      capabilities: ["database.view", "database.update", "database.delete", "ground_truth.view", "ground_truth.edit", "ground_truth.accept_reject", "run.view"],
      contextGeneration: 1,
      currentWorkspace: { id: "workspace-1", name: "Workspace", role: "owner", isDefault: true, capabilities: [] },
    });
    vi.mocked(listDocuments).mockResolvedValue([]);
  });

  it("keeps viewer settings read-only", () => {
    useWorkspaceStore.setState({ capabilities: ["database.view"] });
    render(<MemoryRouter><SettingsView projectId="workspace-1" projectName="Database" /></MemoryRouter>);

    expect(screen.getByTestId("input-project-name")).toBeDisabled();
    expect(screen.getByTestId("input-project-description")).toBeDisabled();
    expect(screen.getByTestId("btn-save-settings")).toBeDisabled();
    expect(screen.getByTestId("btn-delete-project")).toBeDisabled();
  });

  it("saves settings through the canonical workspace PATCH", async () => {
    vi.mocked(updateDatabaseSettings).mockResolvedValue({ id: "workspace-1", name: "Renamed", description: "Updated" });
    render(<MemoryRouter><SettingsView projectId="workspace-1" projectName="Database" /></MemoryRouter>);

    fireEvent.change(screen.getByTestId("input-project-name"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByTestId("btn-save-settings"));

    await waitFor(() => expect(updateDatabaseSettings).toHaveBeenCalledWith("workspace-1", { name: "Renamed", description: "" }));
  });

  it("requires a selected document before ground-truth upload", async () => {
    vi.mocked(listDocuments).mockResolvedValue([{ id: "doc-1", projectId: "project-1", filename: "one.pdf", type: "PDF", size: 1, uploadedAt: "2026-01-01T00:00:00Z", gtStatus: "none" }]);
    render(<GroundTruthView projectId="project-1" />);
    await screen.findByText("one.pdf");

    const input = screen.getByTestId("gt-file-input");
    const clickSpy = vi.spyOn(input, "click");
    fireEvent.click(screen.getByTestId("btn-upload-gt"));
    expect(clickSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("one.pdf"));
    fireEvent.click(screen.getByTestId("btn-upload-gt"));
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("rolls back an optimistic accept when the canonical request fails", async () => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockResolvedValue({ status: "completed", completedCount: 1, totalDocuments: 1 });
    vi.mocked(getRunResults).mockResolvedValue([{ id: "result-1", runId: "run-1", documentId: "doc-1", documentName: "one.pdf", status: "differs", executionStatus: "completed", hasGroundTruth: true, acceptedAsGT: false }]);
    vi.mocked(acceptAsGT).mockRejectedValue(new Error("conflict"));
    render(<ActiveRunHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Monitor" }));
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(screen.getByTestId("accepted")).toHaveTextContent("false");

    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await act(async () => Promise.resolve());
    expect(screen.getByTestId("accepted")).toHaveTextContent("false");
    vi.useRealTimers();
  });
});
