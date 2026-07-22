import { App as AntApp } from "antd";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDocAnnotationRunData } from "@/features/doc-annotation/hooks/useDocAnnotationRunData";
import {
  createEvaluationRun,
  generateClientRequestId,
  getEvaluationRun,
  getEvaluationRunResults,
} from "@/services/evaluationRunApi";
import { getWorkflowList } from "@/services/workflowApi";

vi.mock("@/services/evaluationRunApi", () => ({
  createEvaluationRun: vi.fn(),
  generateClientRequestId: vi.fn(),
  getEvaluationResultDetail: vi.fn(),
  getEvaluationRun: vi.fn(),
  getEvaluationRunResults: vi.fn(),
  isEvaluationRunTerminalStatus: (status: string) => ["completed", "partial_completed", "failed", "cancelled"].includes(status),
}));

vi.mock("@/services/workflowApi", () => ({
  getWorkflowList: vi.fn(),
}));

function wrapper({ children }: { readonly children: ReactNode }) {
  return <AntApp>{children}</AntApp>;
}

const terminalRun = (status: "partial_completed" | "cancelled") => ({
  id: "run-1",
  name: "Evaluation",
  test_set_id: "test-set-1",
  workflow_id: "workflow-1",
  workflow_version: 1,
  status,
  total_documents: 5,
  completed_count: 3,
  failed_count: 1,
  started_at: "2026-07-20T00:00:00Z",
  completed_at: "2026-07-20T00:00:01Z",
  duration_ms: 1000,
  created_at: "2026-07-20T00:00:00Z",
});

const resultsResponse = {
  evaluation_run_id: "run-1",
  status: "partial_completed" as const,
  summary: { total: 5, completed: 1, failed: 1, queued: 1, running: 1, skipped: 1 },
  results: [
    { id: "queued", document_id: "queued", filename: "queued.pdf", status: "queued" as const, processing_time_ms: null, output_format: null, error: null },
    { id: "running", document_id: "running", filename: "running.pdf", status: "running" as const, processing_time_ms: null, output_format: null, error: null },
    { id: "completed", document_id: "completed", filename: "completed.pdf", status: "completed" as const, processing_time_ms: 1, output_format: "text", error: null },
    { id: "failed", document_id: "failed", filename: "failed.pdf", status: "failed" as const, processing_time_ms: null, output_format: null, error: "failed" },
    { id: "skipped", document_id: "skipped", filename: "skipped.pdf", status: "skipped" as const, processing_time_ms: null, output_format: null, error: null },
  ],
};

describe("useDocAnnotationRunData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [{ id: "workflow-1", workflow_key: "workflow", name: "Workflow", description: undefined, created_at: "2026-07-20T00:00:00Z", updated_at: "2026-07-20T00:00:00Z", published_version: 1, latest_version: 1, created_by: null, last_saved_by: null }],
      meta: { total: 1, page: 1, limit: 200 },
    });
    vi.mocked(generateClientRequestId).mockReturnValue("cli_req_test");
    vi.mocked(getEvaluationRunResults).mockResolvedValue(resultsResponse);
  });

  it.each(["partial_completed", "cancelled"] as const)("loads terminal %s runs without scheduling another poll", async (status) => {
    vi.mocked(createEvaluationRun).mockResolvedValue(terminalRun(status));

    const { result } = renderHook(
      () => useDocAnnotationRunData({ selectedTestSetId: "test-set-1", documentCount: 5 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.workflows).toHaveLength(1));
    act(() => result.current.setSelectedWorkflowId("workflow-1"));

    await act(async () => {
      await result.current.startRun();
    });

    expect(result.current.activeRun?.status).toBe(status);
    expect(result.current.runResults.map((item) => item.status)).toEqual([
      "queued",
      "running",
      "completed",
      "failed",
      "skipped",
    ]);
    expect(getEvaluationRun).not.toHaveBeenCalled();
  });

  it("shows the server conflict code and message when starting a run is rejected", async () => {
    const conflict = new AxiosError("Request failed");
    conflict.response = {
      data: { error: { code: "ACTIVE_RUN_EXISTS", message: "已有執行中的評估作業" } },
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: { headers: new AxiosHeaders() },
    };
    vi.mocked(createEvaluationRun).mockRejectedValue(conflict);

    const { result } = renderHook(
      () => useDocAnnotationRunData({ selectedTestSetId: "test-set-1", documentCount: 5 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.workflows).toHaveLength(1));
    act(() => result.current.setSelectedWorkflowId("workflow-1"));

    await act(async () => {
      await result.current.startRun();
    });

    await waitFor(() => {
      expect(result.current.pollWarning).toBe("ACTIVE_RUN_EXISTS: 已有執行中的評估作業");
    });
    expect(await screen.findByText("ACTIVE_RUN_EXISTS: 已有執行中的評估作業")).toBeInTheDocument();
  });
});
