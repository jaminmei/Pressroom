import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DocumentGroundTruthPanel from "@/features/projects/components/DocumentGroundTruthPanel";
import {
  useDocumentGroundTruth,
  type UseDocumentGroundTruthResult,
} from "@/features/projects/hooks/useDocumentGroundTruth";

vi.mock("@/features/projects/hooks/useDocumentGroundTruth", () => ({
  useDocumentGroundTruth: vi.fn(),
}));

const selectVersion = vi.fn();
const retry = vi.fn();
const retrySelectedVersion = vi.fn();

function createResult(
  overrides: Partial<UseDocumentGroundTruthResult> = {},
): UseDocumentGroundTruthResult {
  const current = {
    id: "gt-2",
    projectId: "project-1",
    documentId: "doc-1",
    version: 2,
    source: "review_accept",
    format: "json",
    content: '{"invoice":"25107","amount":42}',
    notes: "Accepted after review",
    createdAt: "2026-07-21T01:00:00Z",
  };
  return {
    versions: [
      current,
      {
        id: "gt-1",
        projectId: "project-1",
        documentId: "doc-1",
        version: 1,
        source: "manual_edit",
        format: "text",
        notes: undefined,
        createdAt: "2026-07-20T01:00:00Z",
      },
    ],
    selectedVersion: 2,
    selectedGroundTruth: current,
    currentVersion: 2,
    loading: false,
    error: null,
    detailLoading: false,
    detailError: null,
    selectVersion,
    retry,
    retrySelectedVersion,
    ...overrides,
  };
}

describe("DocumentGroundTruthPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useDocumentGroundTruth).mockReturnValue(createResult());
  });

  it("renders current metadata, formatted JSON, and selectable history", () => {
    render(<DocumentGroundTruthPanel documentId="doc-1" projectId="project-1" />);

    expect(screen.getByTestId("document-gt-summary")).toHaveTextContent("Version v2");
    expect(screen.getByTestId("document-gt-summary")).toHaveTextContent("Current");
    expect(screen.getByTestId("document-gt-summary")).toHaveTextContent("Accepted from run");
    expect(screen.getByTestId("document-gt-content")).toHaveTextContent(
      '"invoice": "25107"',
    );
    expect(screen.getByTestId("document-gt-history")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("document-gt-version-1"));
    expect(selectVersion).toHaveBeenCalledWith(1);
    expect(screen.queryByText("Upload GT")).not.toBeInTheDocument();
    expect(screen.queryByText("Accept as GT")).not.toBeInTheDocument();
    expect(screen.queryByText("Edit Ground Truth")).not.toBeInTheDocument();
  });

  it("renders a read-only empty state without actions", () => {
    vi.mocked(useDocumentGroundTruth).mockReturnValue(createResult({
      versions: [],
      selectedVersion: null,
      selectedGroundTruth: null,
      currentVersion: null,
    }));

    render(<DocumentGroundTruthPanel documentId="doc-empty" projectId="project-1" />);

    expect(screen.getByTestId("document-gt-empty")).toHaveTextContent("No ground truth yet");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("retries panel and historical-detail failures independently", () => {
    vi.mocked(useDocumentGroundTruth).mockReturnValue(createResult({
      error: "Request failed",
    }));
    const view = render(
      <DocumentGroundTruthPanel documentId="doc-1" projectId="project-1" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);

    vi.mocked(useDocumentGroundTruth).mockReturnValue(createResult({
      selectedVersion: 1,
      selectedGroundTruth: null,
      detailError: "Version request failed",
    }));
    view.rerender(
      <DocumentGroundTruthPanel documentId="doc-1" projectId="project-1" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retrySelectedVersion).toHaveBeenCalledTimes(1);
  });
});
