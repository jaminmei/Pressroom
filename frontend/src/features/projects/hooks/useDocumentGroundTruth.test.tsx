import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDocumentGroundTruth } from "@/features/projects/hooks/useDocumentGroundTruth";
import {
  getDocumentGroundTruthVersion,
  getLatestDocumentGroundTruth,
  listDocumentGroundTruthVersions,
} from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { DocumentGroundTruth } from "@/types/project";

vi.mock("@/services/projectApi", () => ({
  getDocumentGroundTruthVersion: vi.fn(),
  getLatestDocumentGroundTruth: vi.fn(),
  listDocumentGroundTruthVersions: vi.fn(),
}));

const current: DocumentGroundTruth = {
  id: "gt-2",
  projectId: "project-1",
  documentId: "doc-1",
  version: 2,
  source: "inference_apply",
  format: "markdown",
  content: "# current",
  notes: "accepted",
  createdAt: "2026-07-21T01:00:00Z",
};

const historical: DocumentGroundTruth = {
  id: "gt-1",
  projectId: "project-1",
  documentId: "doc-1",
  version: 1,
  source: "manual_edit",
  format: "text",
  content: "historical",
  createdAt: "2026-07-20T01:00:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("useDocumentGroundTruth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace",
        role: "owner",
        isDefault: true,
        capabilities: ["database.view", "ground_truth.view"],
      },
      contextGeneration: 1,
      capabilities: ["database.view", "ground_truth.view"],
    });
    vi.mocked(getLatestDocumentGroundTruth).mockResolvedValue(current);
    vi.mocked(listDocumentGroundTruthVersions).mockResolvedValue([
      current,
      historical,
    ]);
    vi.mocked(getDocumentGroundTruthVersion).mockResolvedValue(historical);
  });

  it("loads the current version and lazily caches historical content", async () => {
    const { result } = renderHook(() =>
      useDocumentGroundTruth("project-1", "doc-1"),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.selectedGroundTruth).toEqual(current);
    expect(result.current.currentVersion).toBe(2);

    act(() => result.current.selectVersion(1));
    await waitFor(() => expect(result.current.selectedGroundTruth).toEqual(historical));
    expect(getDocumentGroundTruthVersion).toHaveBeenCalledTimes(1);

    act(() => result.current.selectVersion(2));
    act(() => result.current.selectVersion(1));
    expect(result.current.selectedGroundTruth).toEqual(historical);
    expect(getDocumentGroundTruthVersion).toHaveBeenCalledTimes(1);
  });

  it("exposes a true empty state when no versions exist", async () => {
    vi.mocked(getLatestDocumentGroundTruth).mockResolvedValue(null);
    vi.mocked(listDocumentGroundTruthVersions).mockResolvedValue([]);

    const { result } = renderHook(() =>
      useDocumentGroundTruth("project-1", "doc-empty"),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.versions).toEqual([]);
    expect(result.current.selectedGroundTruth).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("ignores a late response after the selected document changes", async () => {
    const oldLatest = deferred<DocumentGroundTruth | null>();
    const oldVersions = deferred<DocumentGroundTruth[]>();
    vi.mocked(getLatestDocumentGroundTruth)
      .mockReturnValueOnce(oldLatest.promise)
      .mockResolvedValueOnce({ ...current, documentId: "doc-2", content: "new document" });
    vi.mocked(listDocumentGroundTruthVersions)
      .mockReturnValueOnce(oldVersions.promise)
      .mockResolvedValueOnce([{ ...current, documentId: "doc-2" }]);

    const { result, rerender } = renderHook(
      ({ documentId }) => useDocumentGroundTruth("project-1", documentId),
      { initialProps: { documentId: "doc-1" } },
    );
    rerender({ documentId: "doc-2" });

    await waitFor(() =>
      expect(result.current.selectedGroundTruth?.documentId).toBe("doc-2"),
    );
    oldLatest.resolve(current);
    oldVersions.resolve([current]);
    await act(async () => Promise.all([oldLatest.promise, oldVersions.promise]));

    expect(result.current.selectedGroundTruth?.documentId).toBe("doc-2");
    expect(result.current.selectedGroundTruth?.content).toBe("new document");
  });

  it("retries both initial and selected-version failures", async () => {
    vi.mocked(getLatestDocumentGroundTruth)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(current);

    const { result } = renderHook(() =>
      useDocumentGroundTruth("project-1", "doc-1"),
    );
    await waitFor(() => expect(result.current.error).toBe("Failed to load ground truth."));

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.selectedGroundTruth).toEqual(current));

    vi.mocked(getDocumentGroundTruthVersion)
      .mockRejectedValueOnce(new Error("detail offline"))
      .mockResolvedValue(historical);
    act(() => result.current.selectVersion(1));
    await waitFor(() =>
      expect(result.current.detailError).toBe("Failed to load this ground-truth version."),
    );

    act(() => result.current.retrySelectedVersion());
    await waitFor(() => expect(result.current.selectedGroundTruth).toEqual(historical));
  });
});
