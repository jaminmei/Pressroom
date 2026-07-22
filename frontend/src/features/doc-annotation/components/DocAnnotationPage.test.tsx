import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DocAnnotationPage from "@/features/doc-annotation/components/DocAnnotationPage";
import {
  createEvaluationRun,
  generateClientRequestId,
  getEvaluationResultDetail,
  getEvaluationRun,
  getEvaluationRunResults
} from "@/services/evaluationRunApi";
import {
  getOriginalDocumentDownloadUrl,
  listTestSetDocuments,
  listTestSets,
  uploadTestSetDocuments
} from "@/services/testSetApi";
import { getWorkflowList } from "@/services/workflowApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { TestDocumentUploadResponse } from "@/types/testSet";

vi.mock("@/services/testSetApi", () => ({
  listTestSets: vi.fn(),
  listTestSetDocuments: vi.fn(),
  uploadTestSetDocuments: vi.fn(),
  getOriginalDocumentDownloadUrl: vi.fn()
}));

vi.mock("@/services/workflowApi", () => ({
  getWorkflowList: vi.fn()
}));

vi.mock("@/services/evaluationRunApi", () => ({
  createEvaluationRun: vi.fn(),
  generateClientRequestId: vi.fn(),
  getEvaluationRun: vi.fn(),
  getEvaluationRunResults: vi.fn(),
  getEvaluationResultDetail: vi.fn(),
  isEvaluationRunTerminalStatus: (status: string) => ["completed", "partial_completed", "failed", "cancelled"].includes(status)
}));

const sampleTestSet = {
  id: "ts_1",
  name: "Invoices",
  description: "OCR smoke set",
  document_count: 1,
  created_at: "2026-04-28T00:00:00Z",
  updated_at: "2026-04-28T00:00:00Z"
};

const sampleDocument = {
  id: "doc_1",
  test_set_id: "ts_1",
  filename: "invoice.pdf",
  mime_type: "application/pdf",
  size_bytes: 12,
  page_count: 1,
  has_ground_truth: false,
  gt_version_count: 0,
  created_at: "2026-04-28T00:00:00Z"
};

const sampleWorkflow = {
  id: "wf_1",
  workflow_key: "ocr-eval",
  name: "OCR Eval",
  description: "Evaluation workflow",
  created_at: "2026-04-28T00:00:00Z",
  updated_at: "2026-04-28T00:00:00Z",
  published_version: 3,
  latest_version: 3,
  created_by: null,
  last_saved_by: null
};

type DocumentListResponse = {
  items: typeof sampleDocument[];
  total: number;
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AntApp>
        <DocAnnotationPage />
      </AntApp>
    </MemoryRouter>
  );
}

async function selectTestSet() {
  fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Test set selector" }));
  fireEvent.click(await screen.findByText("Invoices"));

  await waitFor(() => {
    expect(listTestSetDocuments).toHaveBeenCalledWith("ts_1");
  });
}

async function selectTestSetByName(name: string, id: string) {
  fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Test set selector" }));
  fireEvent.click(await screen.findByText(name));

  await waitFor(() => {
    expect(listTestSetDocuments).toHaveBeenCalledWith(id);
  });
}

describe("DocAnnotationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(listTestSets).mockResolvedValue({
      items: [sampleTestSet],
      total: 1
    });
    vi.mocked(listTestSetDocuments).mockResolvedValue({
      items: [sampleDocument],
      total: 1
    });
    vi.mocked(uploadTestSetDocuments).mockResolvedValue({
      uploaded: [
        {
          id: "doc_1",
          filename: "invoice.pdf",
          mime_type: "application/pdf",
          size_bytes: 12
        }
      ],
      errors: []
    });
    vi.mocked(getOriginalDocumentDownloadUrl).mockImplementation(
      (testSetId: string, documentId: string) =>
        `/api/test-sets/${testSetId}/documents/${documentId}/file`
    );
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });
    vi.mocked(createEvaluationRun).mockResolvedValue({
      id: "run_1",
      name: "OCR Eval Run",
      test_set_id: "ts_1",
      workflow_id: "wf_1",
      workflow_version: 3,
      status: "pending",
      total_documents: 1,
      completed_count: 0,
      failed_count: 0,
      started_at: null,
      completed_at: null,
      duration_ms: null,
      created_at: "2026-04-29T00:00:00Z"
    });
    vi.mocked(generateClientRequestId).mockReturnValue("cli_req_test");
    vi.mocked(getEvaluationRun).mockResolvedValue({
      id: "run_1",
      name: "OCR Eval Run",
      test_set_id: "ts_1",
      workflow_id: "wf_1",
      workflow_version: 3,
      status: "completed",
      total_documents: 1,
      completed_count: 1,
      failed_count: 0,
      started_at: "2026-04-29T00:00:00Z",
      completed_at: "2026-04-29T00:00:10Z",
      duration_ms: 10000,
      created_at: "2026-04-29T00:00:00Z"
    });
    vi.mocked(getEvaluationRunResults).mockResolvedValue({
      evaluation_run_id: "run_1",
      status: "completed",
      summary: {
        total: 1,
        completed: 1,
        failed: 0,
        queued: 0,
        running: 0,
        skipped: 0
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
    });
    vi.mocked(getEvaluationResultDetail).mockResolvedValue({
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
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: ["database.view"]
      },
      contextGeneration: 1
    });
  });

  it("renders the minimal runner shell sections with disabled prerequisite actions", async () => {
    renderPage();

    expect(screen.getByText("Doc Annotation")).toBeInTheDocument();
    expect(
      screen.getByText("Select an existing test set to start the minimal evaluation runner flow.")
    ).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Upload documents" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start batch run" })).toBeDisabled();
    expect(await screen.findAllByText("Select a test set first.")).toHaveLength(3);
    expect(listTestSets).toHaveBeenCalledTimes(1);
  });

  it("loads uploaded documents for the selected test set and exposes original download links", async () => {
    renderPage();

    await selectTestSet();

    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    const downloadLink = screen.getByRole("link", { name: "Download original" });
    expect(downloadLink).toHaveAttribute("href", "/api/test-sets/ts_1/documents/doc_1/file");
  });

  it("uploads queued files, refreshes the document list, and shows per-file upload errors", async () => {
    vi.mocked(listTestSetDocuments)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [sampleDocument], total: 1 });
    vi.mocked(uploadTestSetDocuments).mockResolvedValue({
      uploaded: [
        {
          id: "doc_1",
          filename: "invoice.pdf",
          mime_type: "application/pdf",
          size_bytes: 12
        }
      ],
      errors: [
        {
          filename: "notes.txt",
          error: "Unsupported file type: text/plain"
        }
      ]
    });

    const { container } = renderPage();

    await selectTestSet();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    const txt = new File(["notes"], "notes.txt", { type: "text/plain" });

    fireEvent.change(input, { target: { files: [pdf, txt] } });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Upload documents" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    await waitFor(() => {
      expect(uploadTestSetDocuments).toHaveBeenCalledWith("ts_1", [pdf, txt]);
    });

    expect(await screen.findByText("Uploaded 1 document.")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.getByText("Unsupported file type: text/plain")).toBeInTheDocument();
    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
  });

  it("keeps queued files when the picker is used multiple times before upload", async () => {
    vi.mocked(listTestSetDocuments).mockResolvedValue({ items: [], total: 0 });

    const { container } = renderPage();

    await selectTestSet();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    const png = new File(["png"], "scan.png", { type: "image/png" });

    fireEvent.change(input, { target: { files: [pdf] } });
    const nextInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(nextInput, { target: { files: [png] } });

    await waitFor(() => {
      expect(screen.getByText("scan.png")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    await waitFor(() => {
      expect(uploadTestSetDocuments).toHaveBeenCalledTimes(1);
    });

    const uploadedFiles = vi.mocked(uploadTestSetDocuments).mock.calls[0]?.[1] ?? [];
    expect(uploadedFiles).toHaveLength(2);
    expect(uploadedFiles.map((file) => file.name)).toEqual(["invoice.pdf", "scan.png"]);
  });

  it("clears queued and upload-result state when switching to another test set", async () => {
    vi.mocked(listTestSets).mockResolvedValue({
      items: [
        sampleTestSet,
        {
          ...sampleTestSet,
          id: "ts_2",
          name: "Receipts",
          description: "Backup set"
        }
      ],
      total: 2
    });
    vi.mocked(listTestSetDocuments)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({
        items: [
          {
            ...sampleDocument,
            id: "doc_2",
            test_set_id: "ts_2",
            filename: "receipt.pdf"
          }
        ],
        total: 1
      });
    vi.mocked(uploadTestSetDocuments).mockResolvedValue({
      uploaded: [
        {
          id: "doc_1",
          filename: "invoice.pdf",
          mime_type: "application/pdf",
          size_bytes: 12
        }
      ],
      errors: []
    });

    const { container } = renderPage();

    await selectTestSetByName("Invoices", "ts_1");

    const firstInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(firstInput, { target: { files: [pdf] } });

    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));
    expect(await screen.findByText("Uploaded 1 document.")).toBeInTheDocument();

    await selectTestSetByName("Receipts", "ts_2");

    expect(screen.queryByText("Uploaded 1 document.")).not.toBeInTheDocument();
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload documents" })).toBeDisabled();
    expect(await screen.findByText("receipt.pdf")).toBeInTheDocument();
  });

  it("shows a dedicated upload failure message when the upload request fails", async () => {
    vi.mocked(listTestSetDocuments).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(uploadTestSetDocuments).mockRejectedValue(new Error("upload failed"));

    const { container } = renderPage();

    await selectTestSet();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [pdf] } });

    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    expect(await screen.findByText("Failed to upload documents.")).toBeInTheDocument();
  });

  it("shows a feature-level error message when test sets fail to load", async () => {
    vi.mocked(listTestSets).mockRejectedValue(new Error("network error"));

    renderPage();

    expect(await screen.findByText("Failed to load test sets.")).toBeInTheDocument();
  });

  it("does not show a late test-set response after the workspace generation changes", async () => {
    let resolveOldRequest: ((value: Awaited<ReturnType<typeof listTestSets>>) => void) | undefined;
    const oldRequest = new Promise<Awaited<ReturnType<typeof listTestSets>>>((resolve) => {
      resolveOldRequest = resolve;
    });
    vi.mocked(listTestSets)
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce({
        items: [{ ...sampleTestSet, id: "ts_new", name: "New Workspace Test Set" }],
        total: 1
      });

    renderPage();
    await waitFor(() => expect(listTestSets).toHaveBeenCalledTimes(1));

    act(() => {
      useWorkspaceStore.setState({
        currentWorkspace: {
          id: "workspace-2",
          name: "Workspace 2",
          role: "owner",
          isDefault: false,
          capabilities: ["database.view"]
        },
        contextGeneration: 2
      });
    });

    await waitFor(() => expect(listTestSets).toHaveBeenCalledTimes(2));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Test set selector" }));
    expect(await screen.findByText("New Workspace Test Set")).toBeInTheDocument();
    await act(async () => {
      resolveOldRequest?.({ items: [sampleTestSet], total: 1 });
      await oldRequest;
    });

    await waitFor(() => {
      expect(screen.queryByText("Invoices")).not.toBeInTheDocument();
      expect(screen.getByText("New Workspace Test Set")).toBeInTheDocument();
    });
  });

  it("shows a loading state instead of an empty-state message while documents are loading", async () => {
    vi.mocked(listTestSetDocuments).mockImplementationOnce(() => new Promise(() => undefined));

    renderPage();

    await selectTestSet();

    expect(screen.getByText("Loading documents...")).toBeInTheDocument();
    expect(screen.queryByText("No documents in this test set yet.")).not.toBeInTheDocument();
  });

  it("clears stale success state when a follow-up upload fails", async () => {
    vi.mocked(listTestSetDocuments)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [sampleDocument], total: 1 });
    vi.mocked(uploadTestSetDocuments)
      .mockResolvedValueOnce({
        uploaded: [
          {
            id: "doc_1",
            filename: "invoice.pdf",
            mime_type: "application/pdf",
            size_bytes: 12
          }
        ],
        errors: []
      })
      .mockRejectedValueOnce(new Error("upload failed"));

    const { container } = renderPage();

    await selectTestSet();

    const firstInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const firstFile = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(firstInput, { target: { files: [firstFile] } });

    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    expect(await screen.findByText("Uploaded 1 document.")).toBeInTheDocument();

    const secondInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const secondFile = new File(["png"], "scan.png", { type: "image/png" });
    fireEvent.change(secondInput, { target: { files: [secondFile] } });

    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    expect(await screen.findByText("Failed to upload documents.")).toBeInTheDocument();
    expect(screen.queryByText("Uploaded 1 document.")).not.toBeInTheDocument();
  });

  it("ignores stale document responses when switching test sets quickly", async () => {
    let resolveFirstRequest: ((value: DocumentListResponse) => void) | undefined;

    vi.mocked(listTestSets).mockResolvedValue({
      items: [
        sampleTestSet,
        {
          ...sampleTestSet,
          id: "ts_2",
          name: "Receipts"
        }
      ],
      total: 2
    });
    vi.mocked(listTestSetDocuments)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirstRequest = resolve;
          })
      )
      .mockResolvedValueOnce({
        items: [
          {
            ...sampleDocument,
            id: "doc_2",
            test_set_id: "ts_2",
            filename: "receipt.pdf"
          }
        ],
        total: 1
      });

    renderPage();

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Test set selector" }));
    fireEvent.click(await screen.findByText("Invoices"));

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Test set selector" }));
    fireEvent.click(await screen.findByText("Receipts"));

    expect(await screen.findByText("receipt.pdf")).toBeInTheDocument();

    resolveFirstRequest?.({
      items: [sampleDocument],
      total: 1
    });

    await waitFor(() => {
      expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    });
  });

  it("ignores stale upload completions after switching to another test set", async () => {
    let resolveUpload: ((value: TestDocumentUploadResponse) => void) | undefined;

    vi.mocked(listTestSets).mockResolvedValue({
      items: [
        sampleTestSet,
        {
          ...sampleTestSet,
          id: "ts_2",
          name: "Receipts",
          description: "Backup set"
        }
      ],
      total: 2
    });
    vi.mocked(listTestSetDocuments)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({
        items: [
          {
            ...sampleDocument,
            id: "doc_2",
            test_set_id: "ts_2",
            filename: "receipt.pdf"
          }
        ],
        total: 1
      })
      .mockResolvedValueOnce({ items: [sampleDocument], total: 1 });
    vi.mocked(uploadTestSetDocuments).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve;
        })
    );

    const { container } = renderPage();

    await selectTestSetByName("Invoices", "ts_1");

    const firstInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(firstInput, { target: { files: [pdf] } });

    fireEvent.click(screen.getByRole("button", { name: "Upload documents" }));

    await waitFor(() => {
      expect(uploadTestSetDocuments).toHaveBeenCalledWith("ts_1", [pdf]);
    });

    await selectTestSetByName("Receipts", "ts_2");
    expect(await screen.findByText("receipt.pdf")).toBeInTheDocument();

    resolveUpload?.({
      uploaded: [
        {
          id: "doc_1",
          filename: "invoice.pdf",
          mime_type: "application/pdf",
          size_bytes: 12
        }
      ],
      errors: []
    });

    await waitFor(() => {
      expect(screen.queryByText("Uploaded 1 document.")).not.toBeInTheDocument();
      expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
      expect(screen.getByText("receipt.pdf")).toBeInTheDocument();
    });
  });

  it("loads workflow options for the selected test set and starts a batch run after a workflow is chosen", async () => {
    renderPage();

    await selectTestSet();

    expect(screen.getByRole("button", { name: "Start batch run" })).toBeDisabled();

    const workflowSelector = screen.getByRole("combobox", { name: "Workflow selector" });
    fireEvent.mouseDown(workflowSelector);
    fireEvent.click(await screen.findByText("OCR Eval"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Start batch run" })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Start batch run" }));

    await waitFor(() => {
      expect(createEvaluationRun).toHaveBeenCalledWith("ts_1", {
        workflow_id: "wf_1",
        client_request_id: "cli_req_test"
      });
    });
  });

  it("polls the active evaluation run, shows counters, and lazy-loads result detail", async () => {
    vi.mocked(getEvaluationRun)
      .mockResolvedValueOnce({
        id: "run_1",
        name: "OCR Eval Run",
        test_set_id: "ts_1",
        workflow_id: "wf_1",
        workflow_version: 3,
        status: "running",
        total_documents: 1,
        completed_count: 0,
        failed_count: 0,
        started_at: "2026-04-29T00:00:00Z",
        completed_at: null,
        duration_ms: null,
        created_at: "2026-04-29T00:00:00Z"
      })
      .mockResolvedValueOnce({
        id: "run_1",
        name: "OCR Eval Run",
        test_set_id: "ts_1",
        workflow_id: "wf_1",
        workflow_version: 3,
        status: "completed",
        total_documents: 1,
        completed_count: 1,
        failed_count: 0,
        started_at: "2026-04-29T00:00:00Z",
        completed_at: "2026-04-29T00:00:10Z",
        duration_ms: 10000,
        created_at: "2026-04-29T00:00:00Z"
      });

    renderPage();

    await selectTestSet();

    const workflowSelector = screen.getByRole("combobox", { name: "Workflow selector" });
    fireEvent.mouseDown(workflowSelector);
    fireEvent.click(await screen.findByText("OCR Eval"));
    fireEvent.click(screen.getByRole("button", { name: "Start batch run" }));

    await waitFor(() => {
      expect(getEvaluationRun).toHaveBeenCalledWith("run_1");
    });

    await waitFor(() => {
      expect(getEvaluationRun).toHaveBeenCalledTimes(2);
    }, { timeout: 5000 });

    await waitFor(() => {
      expect(screen.getByText("Completed: 1 / 1")).toBeInTheDocument();
    });

    expect(screen.getByText("Failed: 0")).toBeInTheDocument();
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View result detail" }));

    await waitFor(() => {
      expect(getEvaluationResultDetail).toHaveBeenCalledWith("run_1", "result_1");
    });

    expect(await screen.findByText("# Invoice")).toBeInTheDocument();
  }, 15000);
});
