import { App as AntApp } from "antd";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useActiveRun } from "@/features/projects/hooks/useActiveRun";
import { acceptAsGT, getRunResults, getRunStatus, rejectResult } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/services/projectApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/projectApi")>("@/services/projectApi");
  return {
    ...actual,
    acceptAsGT: vi.fn(),
    getRunResults: vi.fn(),
    getRunStatus: vi.fn(),
    rejectResult: vi.fn(),
  };
});

function wrapper({ children }: { readonly children: ReactNode }) {
  return <AntApp>{children}</AntApp>;
}

const progressResults = [
  { id: "result-queued", runId: "run-1", documentId: "queued", documentName: "queued.pdf", status: "unknown", executionStatus: "queued", hasGroundTruth: false, acceptedAsGT: false },
  { id: "result-running", runId: "run-1", documentId: "running", documentName: "running.pdf", status: "unknown", executionStatus: "running", hasGroundTruth: false, acceptedAsGT: false },
  { id: "result-completed", runId: "run-1", documentId: "completed", documentName: "completed.pdf", status: "unknown", executionStatus: "completed", hasGroundTruth: false, acceptedAsGT: false },
  { id: "result-failed", runId: "run-1", documentId: "failed", documentName: "failed.pdf", status: "failed", executionStatus: "failed", hasGroundTruth: false, acceptedAsGT: false },
  { id: "result-skipped", runId: "run-1", documentId: "skipped", documentName: "skipped.pdf", status: "skipped", executionStatus: "skipped", hasGroundTruth: false, acceptedAsGT: false },
] as const;

describe("useActiveRun", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: [],
      },
      capabilities: ["run.view"],
      contextGeneration: 1,
    });
  });

  it.each([
    "partial_completed",
    "cancelled",
  ] as const)("stops polling and preserves the %s terminal state", async (terminalStatus) => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: terminalStatus,
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([]);

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });

    act(() => result.current.startMonitoring("run-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.runStatus).toBe(terminalStatus);
    expect(getRunStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(getRunStatus).toHaveBeenCalledTimes(1);
  });

  it("preserves pending while a queue-backed run waits to start", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "pending",
      completedCount: 0,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([]);

    const { result, unmount } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));
    expect(result.current.runStatus).toBe("pending");

    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(result.current.runStatus).toBe("pending");
    unmount();
  });

  it("stops polling and clears run data when run.view is revoked", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "running",
      completedCount: 0,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-1",
        runId: "run-1",
        documentId: "doc-1",
        documentName: "one.pdf",
        status: "running",
        executionStatus: "running",
        hasGroundTruth: false,
        acceptedAsGT: false,
      },
    ]);

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(getRunStatus).toHaveBeenCalledTimes(1);
    expect(result.current.results).toHaveLength(1);

    act(() => {
      useWorkspaceStore.setState({
        capabilities: [],
        currentWorkspace: {
          id: "workspace-1",
          name: "Workspace 1",
          role: "viewer",
          isDefault: true,
          capabilities: [],
        },
      });
    });

    expect(result.current.activeRunId).toBeNull();
    expect(result.current.runStatus).toBe("idle");
    expect(result.current.results).toEqual([]);
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(getRunStatus).toHaveBeenCalledTimes(1);
    expect(getRunResults).toHaveBeenCalledTimes(1);
  });

  it("maps every evaluation result state into document progress", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "running",
      completedCount: 1,
      totalDocuments: 5,
    });
    vi.mocked(getRunResults).mockResolvedValue([...progressResults]);

    const { result, unmount } = renderHook(() => useActiveRun("project-1"), { wrapper });

    act(() => result.current.startMonitoring("run-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.runProgress).toEqual([
      { documentId: "queued", documentName: "queued.pdf", status: "pending" },
      { documentId: "running", documentName: "running.pdf", status: "processing" },
      { documentId: "completed", documentName: "completed.pdf", status: "complete" },
      { documentId: "failed", documentName: "failed.pdf", status: "failed" },
      { documentId: "skipped", documentName: "skipped.pdf", status: "skipped" },
    ]);

    unmount();
  });

  it("reveals documents completing across consecutive polls", async () => {
    vi.mocked(getRunStatus)
      .mockResolvedValueOnce({ status: "running", completedCount: 0, totalDocuments: 2 })
      .mockResolvedValueOnce({ status: "running", completedCount: 1, totalDocuments: 2 })
      .mockResolvedValueOnce({ status: "completed", completedCount: 2, totalDocuments: 2 });
    vi.mocked(getRunResults)
      .mockResolvedValueOnce([
        { id: "result-1", runId: "run-1", documentId: "doc-1", documentName: "one.pdf", status: "unknown", executionStatus: "queued", hasGroundTruth: false, acceptedAsGT: false },
        { id: "result-2", runId: "run-1", documentId: "doc-2", documentName: "two.pdf", status: "unknown", executionStatus: "queued", hasGroundTruth: false, acceptedAsGT: false },
      ])
      .mockResolvedValueOnce([
        { id: "result-1", runId: "run-1", documentId: "doc-1", documentName: "one.pdf", status: "unknown", executionStatus: "completed", hasGroundTruth: false, acceptedAsGT: false },
        { id: "result-2", runId: "run-1", documentId: "doc-2", documentName: "two.pdf", status: "unknown", executionStatus: "running", hasGroundTruth: false, acceptedAsGT: false },
      ])
      .mockResolvedValueOnce([
        { id: "result-1", runId: "run-1", documentId: "doc-1", documentName: "one.pdf", status: "unknown", executionStatus: "completed", hasGroundTruth: false, acceptedAsGT: false },
        { id: "result-2", runId: "run-1", documentId: "doc-2", documentName: "two.pdf", status: "unknown", executionStatus: "completed", hasGroundTruth: false, acceptedAsGT: false },
      ]);

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));

    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(result.current.runProgress.map((item) => item.status)).toEqual(["pending", "pending"]);

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.runProgress.map((item) => item.status)).toEqual(["complete", "processing"]);

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.runProgress.map((item) => item.status)).toEqual(["complete", "complete"]);
    expect(result.current.runStatus).toBe("completed");
  });

  it("updates comparison and GT availability without restarting monitoring", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "completed",
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-1",
        runId: "run-1",
        documentId: "doc-1",
        documentName: "one.pdf",
        status: "unknown",
        executionStatus: "completed",
        hasGroundTruth: true,
        acceptedAsGT: false,
      },
    ]);

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));
    await act(async () => vi.advanceTimersByTimeAsync(500));

    act(() => result.current.updateResultComparison("result-1", "matched"));
    expect(result.current.results[0]).toMatchObject({
      status: "pass",
      hasGroundTruth: true,
    });

    act(() => result.current.updateResultComparison("result-1", "unavailable"));
    expect(result.current.results[0]).toMatchObject({
      status: "no_gt",
      hasGroundTruth: false,
    });
    expect(getRunStatus).toHaveBeenCalledTimes(1);
  });

  it("rolls back GT availability when optimistic acceptance fails", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "completed",
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-1",
        runId: "run-1",
        documentId: "doc-1",
        documentName: "one.pdf",
        status: "no_gt",
        executionStatus: "completed",
        hasGroundTruth: false,
        acceptedAsGT: false,
      },
    ]);
    vi.mocked(acceptAsGT).mockRejectedValue(new Error("accept failed"));

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));
    await act(async () => vi.advanceTimersByTimeAsync(500));

    act(() => result.current.acceptAsGT("doc-1"));
    expect(result.current.results[0]).toMatchObject({
      status: "pass",
      hasGroundTruth: true,
      acceptedAsGT: true,
    });
    await act(async () => Promise.resolve());
    expect(result.current.results[0]).toMatchObject({
      status: "no_gt",
      hasGroundTruth: false,
      acceptedAsGT: false,
    });
  });

  it("rolls back review state without removing existing GT when rejection fails", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      status: "completed",
      completedCount: 1,
      totalDocuments: 1,
    });
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-1",
        runId: "run-1",
        documentId: "doc-1",
        documentName: "one.pdf",
        status: "pass",
        executionStatus: "completed",
        hasGroundTruth: true,
        acceptedAsGT: true,
        rejected: false,
      },
    ]);
    vi.mocked(rejectResult).mockRejectedValue(new Error("reject failed"));

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });
    act(() => result.current.startMonitoring("run-1"));
    await act(async () => vi.advanceTimersByTimeAsync(500));

    act(() => result.current.rejectResult("doc-1"));
    expect(result.current.results[0]).toMatchObject({
      acceptedAsGT: false,
      hasGroundTruth: true,
      rejected: true,
    });
    await act(async () => Promise.resolve());
    expect(result.current.results[0]).toMatchObject({
      acceptedAsGT: true,
      hasGroundTruth: true,
      rejected: false,
    });
  });

  it("exposes a load error and clears it after a successful retry", async () => {
    vi.mocked(getRunStatus)
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue({
        status: "completed",
        completedCount: 1,
        totalDocuments: 1,
      });
    vi.mocked(getRunResults).mockResolvedValue([
      {
        id: "result-1",
        runId: "run-1",
        documentId: "document-1",
        documentName: "one.pdf",
        status: "pass",
        executionStatus: "completed",
        hasGroundTruth: true,
        acceptedAsGT: false,
      },
    ]);

    const { result } = renderHook(() => useActiveRun("project-1"), { wrapper });

    act(() => result.current.startMonitoring("run-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.error).toBe("Failed to monitor the evaluation run.");
    expect(result.current.runStatus).toBe("failed");
    expect(result.current.results).toEqual([]);

    act(() => result.current.startMonitoring("run-1"));
    expect(result.current.error).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.runStatus).toBe("completed");
    expect(result.current.results).toHaveLength(1);
    expect(getRunStatus).toHaveBeenCalledTimes(2);
    expect(getRunResults).toHaveBeenCalledTimes(1);
  });
});
