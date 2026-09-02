import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  getDocumentGroundTruthVersion,
  getLatestDocumentGroundTruth,
  getRunResults,
  listRuns,
  listDocumentGroundTruthVersions,
  compareResult,
} from "@/services/projectApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

describe("projectApi run result mapping", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps execution, comparison, and ground-truth availability separate", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        evaluation_run_id: "run-1",
        status: "running",
        summary: { total: 3, completed: 2, failed: 0 },
        results: [
          {
            id: "result-completed",
            document_id: "doc-completed",
            filename: "completed.pdf",
            status: "completed",
            processing_time_ms: 250,
            output_format: "markdown",
            error: null,
            comparison_status: "matched",
            review_status: null,
            has_ground_truth: true,
          },
          {
            id: "result-no-gt",
            document_id: "doc-no-gt",
            filename: "missing.pdf",
            status: "completed",
            processing_time_ms: 300,
            output_format: "markdown",
            error: null,
            comparison_status: "unavailable",
            review_status: null,
            has_ground_truth: false,
          },
          {
            id: "result-running",
            document_id: "doc-running",
            filename: "running.pdf",
            status: "running",
            processing_time_ms: null,
            output_format: null,
            error: null,
            comparison_status: null,
            review_status: null,
            has_ground_truth: false,
          },
        ],
      },
    } as never);

    const results = await getRunResults("run-1");

    expect(results[0]).toMatchObject({
      status: "pass",
      executionStatus: "completed",
      hasGroundTruth: true,
    });
    expect(results[1]).toMatchObject({
      status: "no_gt",
      executionStatus: "completed",
      hasGroundTruth: false,
    });
    expect(results[2]).toMatchObject({
      status: "running",
      executionStatus: "running",
    });
  });

  it("computes pass rate from matched and mismatched comparisons", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        items: [
          {
            id: "run-1",
            name: "Compared run",
            test_set_id: "project-1",
            workflow_id: "workflow-1",
            workflow_version: 1,
            workflow_name: "OCR",
            status: "completed",
            total_documents: 4,
            completed_count: 4,
            failed_count: 0,
            started_at: "2026-07-21T00:00:00Z",
            completed_at: "2026-07-21T00:01:00Z",
            duration_ms: 60000,
            created_at: "2026-07-21T00:00:00Z",
            result_summary: { total: 4, completed: 4, failed: 0, queued: 0, running: 0 },
            review_summary: { accepted: 0, rejected: 0, unreviewed: 4 },
            comparison_summary: { matched: 1, mismatched: 3, not_compared: 0, unavailable: 0 },
          },
        ],
        total: 1,
      },
    } as never);

    await expect(listRuns("project-1")).resolves.toEqual([
      expect.objectContaining({ id: "run-1", passRate: 25 }),
    ]);
  });

  it("maps current and historical ground-truth responses without loading list content", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({
        data: {
          id: "gt-2",
          document_id: "doc-1",
          version: 2,
          source: "inference_apply",
          format: "markdown",
          content: "# current",
          notes: "accepted",
          created_at: "2026-07-21T01:00:00Z",
          source_task_run_id: "task-2",
        },
      } as never)
      .mockResolvedValueOnce({
        data: {
          items: [
            { id: "gt-1", version: 1, source: "manual_edit", format: "text", notes: null, created_at: "2026-07-20T01:00:00Z" },
            { id: "gt-2", version: 2, source: "inference_apply", format: "markdown", notes: "accepted", created_at: "2026-07-21T01:00:00Z", source_task_run_id: "task-2" },
          ],
          total: 2,
        },
      } as never)
      .mockResolvedValueOnce({
        data: {
          id: "gt-1",
          document_id: "doc-1",
          version: 1,
          source: "manual_edit",
          format: "text",
          content: "historical",
          notes: null,
          created_at: "2026-07-20T01:00:00Z",
        },
      } as never);

    await expect(getLatestDocumentGroundTruth("project-1", "doc-1")).resolves.toMatchObject({
      id: "gt-2",
      documentId: "doc-1",
      content: "# current",
      sourceTaskRunId: "task-2",
    });
    await expect(listDocumentGroundTruthVersions("project-1", "doc-1")).resolves.toEqual([
      expect.objectContaining({ id: "gt-2", version: 2 }),
      expect.objectContaining({ id: "gt-1", version: 1 }),
    ]);
    await expect(getDocumentGroundTruthVersion("project-1", "doc-1", 1)).resolves.toMatchObject({
      id: "gt-1",
      version: 1,
      content: "historical",
    });
    expect(vi.mocked(apiClient.get).mock.calls.map(([path]) => path)).toEqual([
      "/test-sets/project-1/documents/doc-1/ground-truth",
      "/test-sets/project-1/documents/doc-1/ground-truth/versions",
      "/test-sets/project-1/documents/doc-1/ground-truth/versions/1",
    ]);
  });

  it("maps a missing latest ground truth to null and preserves other failures", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 404 } })
      .mockRejectedValueOnce(new Error("network unavailable"));

    await expect(getLatestDocumentGroundTruth("project-1", "doc-1")).resolves.toBeNull();
    await expect(getLatestDocumentGroundTruth("project-1", "doc-1")).rejects.toThrow(
      "network unavailable",
    );
  });

  it("reads comparisons through the canonical read-only endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        result_id: "result-1",
        document_id: "doc-1",
        comparison_status: "matched",
        expected: "expected",
        actual: "expected",
      },
    } as never);

    await compareResult("run-1", "result-1");

    expect(apiClient.get).toHaveBeenCalledWith(
      "/evaluation-runs/run-1/results/result-1/comparison",
    );
  });
});
