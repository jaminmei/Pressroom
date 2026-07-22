import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  createEvaluationRun,
  generateClientRequestId,
  getEvaluationResultDetail,
  getEvaluationRun,
  getEvaluationRunResults,
  isEvaluationRunTerminalStatus
} from "@/services/evaluationRunApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn()
  }
}));

describe("evaluationRunApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates an evaluation run for the selected test set", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        id: "run_1",
        name: "OCR Eval",
        test_set_id: "ts_1",
        workflow_id: "wf_1",
        workflow_version: 3,
        status: "pending",
        total_documents: 2,
        completed_count: 0,
        failed_count: 0,
        started_at: null,
        completed_at: null,
        duration_ms: null,
        created_at: "2026-04-29T00:00:00Z"
      }
    } as never);

    const response = await createEvaluationRun("ts_1", {
      workflow_id: "wf_1",
      name: "OCR Eval"
    });

    expect(apiClient.post).toHaveBeenCalledWith("/test-sets/ts_1/evaluation-runs", {
      workflow_id: "wf_1",
      name: "OCR Eval"
    });
    expect(response.id).toBe("run_1");
    expect(response.status).toBe("pending");
  });

  it("loads the current evaluation run status", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        id: "run_1",
        name: "OCR Eval",
        test_set_id: "ts_1",
        workflow_id: "wf_1",
        workflow_version: 3,
        status: "running",
        total_documents: 2,
        completed_count: 1,
        failed_count: 0,
        started_at: "2026-04-29T00:00:00Z",
        completed_at: null,
        duration_ms: null,
        created_at: "2026-04-29T00:00:00Z"
      }
    } as never);

    const response = await getEvaluationRun("run_1");

    expect(apiClient.get).toHaveBeenCalledWith("/evaluation-runs/run_1");
    expect(response.completed_count).toBe(1);
    expect(response.status).toBe("running");
  });

  it("loads evaluation run results and preserves summary.total", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        evaluation_run_id: "run_1",
        status: "completed",
        summary: {
          total: 2,
          completed: 1,
          failed: 1
        },
        results: [
          {
            id: "result_1",
            document_id: "doc_1",
            filename: "invoice.pdf",
            status: "completed",
            processing_time_ms: 321,
            output_format: "markdown",
            error: null
          }
        ]
      }
    } as never);

    const response = await getEvaluationRunResults("run_1");

    expect(apiClient.get).toHaveBeenCalledWith("/evaluation-runs/run_1/results");
    expect(response.summary.total).toBe(2);
    expect(response.results[0]?.filename).toBe("invoice.pdf");
  });

  it("loads result detail separately from the summary list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        id: "result_1",
        evaluation_run_id: "run_1",
        document_id: "doc_1",
        filename: "invoice.pdf",
        task_run_id: "task_1",
        status: "completed",
        output_content: "# Invoice",
        output_format: "markdown",
        processing_time_ms: 321,
        created_at: "2026-04-29T00:00:00Z",
        error: null
      }
    } as never);

    const response = await getEvaluationResultDetail("run_1", "result_1");

    expect(apiClient.get).toHaveBeenCalledWith("/evaluation-runs/run_1/results/result_1");
    expect(response.output_content).toBe("# Invoice");
    expect(response.task_run_id).toBe("task_1");
  });

  it("forwards client_request_id and document_ids when supplied", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        id: "run_2",
        name: null,
        test_set_id: "ts_1",
        workflow_id: "wf_1",
        workflow_version: 1,
        status: "pending",
        total_documents: 1,
        completed_count: 0,
        failed_count: 0,
        started_at: null,
        completed_at: null,
        duration_ms: null,
        created_at: "2026-04-29T00:00:00Z"
      }
    } as never);

    await createEvaluationRun("ts_1", {
      workflow_id: "wf_1",
      document_ids: ["doc_a"],
      client_request_id: "cli_req_test"
    });

    expect(apiClient.post).toHaveBeenCalledWith("/test-sets/ts_1/evaluation-runs", {
      workflow_id: "wf_1",
      document_ids: ["doc_a"],
      client_request_id: "cli_req_test"
    });
  });

  it("recognizes partial_completed and cancelled as terminal", () => {
    expect(isEvaluationRunTerminalStatus("partial_completed")).toBe(true);
    expect(isEvaluationRunTerminalStatus("cancelled")).toBe(true);
    expect(isEvaluationRunTerminalStatus("completed")).toBe(true);
    expect(isEvaluationRunTerminalStatus("failed")).toBe(true);
    expect(isEvaluationRunTerminalStatus("running")).toBe(false);
    expect(isEvaluationRunTerminalStatus("pending")).toBe(false);
  });

  it("generates unique client_request_id values with the expected prefix", () => {
    const a = generateClientRequestId();
    const b = generateClientRequestId();
    expect(a.startsWith("cli_req_")).toBe(true);
    expect(b.startsWith("cli_req_")).toBe(true);
    expect(a).not.toBe(b);
    expect(a.length).toBe("cli_req_".length + 32);
  });
});
