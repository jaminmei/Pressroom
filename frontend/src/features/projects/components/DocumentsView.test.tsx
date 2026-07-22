import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DocumentsView from "@/features/projects/components/DocumentsView";
import { useDocumentRunHistory } from "@/features/projects/hooks/useDocumentRunHistory";
import { useProjectDocuments } from "@/features/projects/hooks/useProjectDocuments";
import type { DocumentRunHistoryItem, ProjectDocument } from "@/types/project";

vi.mock("@/features/projects/hooks/useProjectDocuments", () => ({
  useProjectDocuments: vi.fn(),
}));

vi.mock("@/features/projects/hooks/useDocumentRunHistory", () => ({
  useDocumentRunHistory: vi.fn(),
}));

vi.mock("@/features/projects/components/DocumentPreview", () => ({
  default: ({ filename }: { filename: string }) => (
    <div data-testid="document-preview">{filename}</div>
  ),
}));

vi.mock("@/features/projects/components/DocumentGroundTruthPanel", () => ({
  default: ({ documentId }: { documentId: string }) => (
    <div data-testid="document-ground-truth-panel">{documentId}</div>
  ),
}));

vi.mock("@/features/projects/components/DocumentThumbnail", () => ({
  default: ({ filename, onPreview }: { filename: string; onPreview: () => void }) => (
    <button data-testid={`thumbnail-${filename}`} onClick={onPreview} type="button">
      {filename}
    </button>
  ),
}));

const document: ProjectDocument = {
  id: "document-1",
  projectId: "project-1",
  filename: "one.jpg",
  type: "image/jpeg",
  size: 1024,
  uploadedAt: "2026-07-20T08:00:00Z",
  gtStatus: "none",
};

const historyItems: DocumentRunHistoryItem[] = [
  {
    runId: "run-latest",
    resultId: "result-latest",
    runName: "Latest evaluation",
    workflowId: "workflow-ocr",
    workflowName: "OCR 1",
    runStatus: "completed",
    resultStatus: "completed",
    processingTimeMs: 4100,
    runDurationMs: 18000,
    comparisonStatus: "matched",
    reviewStatus: "accepted",
    createdAt: "2026-07-20T08:30:00Z",
    completedAt: "2026-07-20T08:30:18Z",
  },
  {
    runId: "run-older",
    resultId: "result-older",
    workflowId: "workflow-ocr",
    workflowName: "OCR 1",
    runStatus: "failed",
    resultStatus: "failed",
    processingTimeMs: 1200,
    error: "OCR timeout",
    createdAt: "2026-07-19T08:30:00Z",
  },
];

describe("DocumentsView document preview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useProjectDocuments).mockReturnValue({
      documents: [document],
      loading: false,
      error: null,
      uploadDocuments: vi.fn(),
      deleteDocument: vi.fn(),
    });
    vi.mocked(useDocumentRunHistory).mockReturnValue({
      items: historyItems,
      total: historyItems.length,
      loading: false,
      error: null,
      retry: vi.fn(),
    });
  });

  it("returns from a selected document preview to the Documents table", () => {
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId(`doc-row-${document.id}`));
    expect(screen.getByTestId("document-preview")).toHaveTextContent(document.filename);
    expect(screen.getByTestId("btn-back-to-documents")).toHaveTextContent(
      "Back to Documents",
    );

    fireEvent.click(screen.getByTestId("btn-back-to-documents"));

    expect(screen.getByTestId("documents-table")).toBeInTheDocument();
    expect(screen.getByTestId(`doc-row-${document.id}`)).toBeInTheDocument();
    expect(screen.queryByTestId("document-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-back-to-documents")).not.toBeInTheDocument();
  });

  it("opens the existing document preview from the filename thumbnail", () => {
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId(`thumbnail-${document.filename}`));

    expect(screen.getByTestId("document-preview")).toHaveTextContent(document.filename);
    expect(screen.getByTestId("btn-back-to-documents")).toBeInTheDocument();
  });

  it("opens the selected document's read-only ground-truth panel", () => {
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId(`doc-row-${document.id}`));
    fireEvent.click(screen.getByRole("tab", { name: "GT" }));

    expect(screen.getByTestId("document-ground-truth-panel")).toHaveTextContent(document.id);
  });

  it.each([
    ["partial_completed", "Run Partially Complete"],
    ["failed", "Run Failed"],
    ["cancelled", "Run Cancelled"],
  ] as const)("preserves per-document states when a run is %s", (runStatus, message) => {
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId="run-terminal"
          monitoredRunId="run-terminal"
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[
            { documentId: "doc-complete", documentName: "complete.pdf", status: "complete" },
            { documentId: "doc-failed", documentName: "failed.pdf", status: "failed" },
            { documentId: "doc-skipped", documentName: "skipped.pdf", status: "skipped" },
          ]}
          runStatus={runStatus}
        />
      </MemoryRouter>,
    );

    const runPanel = screen.getByTestId("tab-run-content");
    expect(within(runPanel).getByText(message)).toBeInTheDocument();
    expect(within(runPanel).getByTestId("run-progress-doc-complete")).toHaveTextContent("Completed");
    expect(within(runPanel).getByTestId("run-progress-doc-failed")).toHaveTextContent("Failed");
    expect(within(runPanel).getByTestId("run-progress-doc-skipped")).toHaveTextContent("Skipped");
    expect(within(runPanel).queryByText(/All 3 documents processed successfully/)).not.toBeInTheDocument();
  });

  it("does not show batch monitoring for a terminal run loaded as history", () => {
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId="run-history"
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[
            { documentId: document.id, documentName: document.filename, status: "complete" },
          ]}
          runStatus="completed"
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("documents-table")).toBeInTheDocument();
    expect(screen.queryByTestId("right-panel")).not.toBeInTheDocument();
    expect(screen.queryByText("Run Monitoring")).not.toBeInTheDocument();
  });

  it("shows only the selected document's latest and prior runs", () => {
    const onViewFullRun = vi.fn();
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={onViewFullRun}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId(`doc-row-${document.id}`));
    fireEvent.click(screen.getByRole("tab", { name: "Runs (2)" }));

    expect(screen.getByText("Latest Run")).toBeInTheDocument();
    expect(screen.getAllByText("OCR 1")).toHaveLength(2);
    expect(screen.getByText("Document 4.1s")).toBeInTheDocument();
    expect(screen.getByText("OCR timeout")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("view-full-run-run-latest"));
    expect(onViewFullRun).toHaveBeenCalledWith("run-latest");
  });

  it("shows loading, empty, and retry states without falling back to batch results", () => {
    vi.mocked(useDocumentRunHistory).mockReturnValue({
      items: [],
      total: 0,
      loading: true,
      error: null,
      retry: vi.fn(),
    });
    const view = render(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId(`doc-row-${document.id}`));
    fireEvent.click(screen.getByRole("tab", { name: "Runs (0)" }));
    expect(screen.getByTestId("document-run-history-loading")).toBeInTheDocument();
    expect(screen.queryByText(/No active run/)).not.toBeInTheDocument();

    const retry = vi.fn();
    vi.mocked(useDocumentRunHistory).mockReturnValue({
      items: [],
      total: 0,
      loading: false,
      error: "History request failed",
      retry,
    });
    view.rerender(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("document-run-history-error")).toHaveTextContent(
      "History request failed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);

    vi.mocked(useDocumentRunHistory).mockReturnValue({
      items: [],
      total: 0,
      loading: false,
      error: null,
      retry,
    });
    view.rerender(
      <MemoryRouter>
        <DocumentsView
          activeRunId={null}
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runStatus="idle"
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("document-run-history-empty")).toHaveTextContent(
      "This document has not been processed yet.",
    );
  });

  it("overlays the current document's live result onto its history entry", () => {
    vi.mocked(useDocumentRunHistory).mockReturnValue({
      items: [{ ...historyItems[0], runId: "run-live", resultStatus: "queued", reviewStatus: "unreviewed" }],
      total: 1,
      loading: false,
      error: null,
      retry: vi.fn(),
    });
    render(
      <MemoryRouter>
        <DocumentsView
          activeRunId="run-live"
          monitoredRunId={null}
          navigate={vi.fn()}
          onViewFullRun={vi.fn()}
          projectId="project-1"
          runProgress={[]}
          runResults={[{
            id: "result-live",
            runId: "run-live",
            documentId: document.id,
            documentName: document.filename,
            status: "pass",
            executionStatus: "completed",
            hasGroundTruth: true,
            acceptedAsGT: true,
          }]}
          runStatus="completed"
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId(`doc-row-${document.id}`));
    fireEvent.click(screen.getByRole("tab", { name: "Runs (1)" }));
    expect(screen.getByText("Accepted as GT")).toBeInTheDocument();
    expect(screen.getByText("Matched")).toBeInTheDocument();
  });
});
