import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDocumentRunHistory } from "@/features/projects/hooks/useDocumentRunHistory";
import { getDocumentRunHistory } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { DocumentRunHistoryPage } from "@/types/project";

vi.mock("@/services/projectApi", () => ({
  getDocumentRunHistory: vi.fn(),
}));

function page(runId: string): DocumentRunHistoryPage {
  return {
    total: 1,
    limit: 20,
    offset: 0,
    items: [{
      runId,
      resultId: `result-${runId}`,
      workflowId: "workflow-1",
      workflowName: "OCR 1",
      runStatus: "completed",
      resultStatus: "completed",
      createdAt: "2026-07-20T08:00:00Z",
    }],
  };
}

describe("useDocumentRunHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getDocumentRunHistory).mockReset();
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: ["run.view"],
      },
      contextGeneration: 1,
      capabilities: ["run.view"],
    });
  });

  it("loads the latest 20 document runs and retries after an error", async () => {
    vi.mocked(getDocumentRunHistory)
      .mockRejectedValueOnce(new Error("request failed"))
      .mockResolvedValueOnce(page("run-retry"));

    const { result } = renderHook(() =>
      useDocumentRunHistory("project-1", "document-1"),
    );
    await waitFor(() =>
      expect(result.current.error).toBe("Failed to load this document's run history."),
    );
    expect(result.current.items).toEqual([]);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.items[0]?.runId).toBe("run-retry"));
    expect(result.current.error).toBeNull();
    expect(getDocumentRunHistory).toHaveBeenLastCalledWith(
      "project-1",
      "document-1",
      20,
      0,
    );
  });

  it("ignores an old response after the workspace changes", async () => {
    let resolveOld: ((value: DocumentRunHistoryPage) => void) | undefined;
    const oldResponse = new Promise<DocumentRunHistoryPage>((resolve) => {
      resolveOld = resolve;
    });
    vi.mocked(getDocumentRunHistory)
      .mockReturnValueOnce(oldResponse)
      .mockResolvedValueOnce(page("run-new-workspace"));

    const { result } = renderHook(() =>
      useDocumentRunHistory("project-1", "document-1"),
    );
    await waitFor(() => expect(getDocumentRunHistory).toHaveBeenCalledTimes(1));

    act(() => {
      useWorkspaceStore.setState({
        currentWorkspace: {
          id: "workspace-2",
          name: "Workspace 2",
          role: "owner",
          isDefault: false,
          capabilities: ["run.view"],
        },
        contextGeneration: 2,
        capabilities: ["run.view"],
      });
    });
    await waitFor(() =>
      expect(result.current.items[0]?.runId).toBe("run-new-workspace"),
    );

    await act(async () => {
      resolveOld?.(page("run-old-workspace"));
      await oldResponse;
    });
    expect(result.current.items[0]?.runId).toBe("run-new-workspace");
  });
});
