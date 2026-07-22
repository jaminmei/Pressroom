import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsView from "@/features/projects/components/RunsView";
import { useProjectRuns } from "@/features/projects/hooks/useProjectRuns";
import { compareResult } from "@/services/projectApi";
import type { ProjectRun, RunResult } from "@/types/project";

vi.mock("@/features/projects/hooks/useProjectRuns", () => ({
  useProjectRuns: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => {
  const can = () => true;
  return { usePermission: () => ({ can }) };
});

vi.mock("@/services/projectApi", () => ({
  compareResult: vi.fn(),
}));

vi.mock("@/features/projects/components/DocumentPreview", () => ({
  default: ({ filename }: { filename: string }) => (
    <div data-testid="document-preview">{filename}</div>
  ),
}));

vi.mock("@/features/projects/components/CompareView", () => ({
  default: ({
    onAcceptAsGT,
    onReject,
  }: {
    onAcceptAsGT?: () => void;
    onReject?: () => void;
  }) => (
    <div data-testid="compare-view">
      {onAcceptAsGT ? <button onClick={onAcceptAsGT}>Accept test</button> : null}
      {onReject ? <button onClick={onReject}>Reject test</button> : null}
    </div>
  ),
}));

const historicalRun: ProjectRun = {
  id: "run-history",
  projectId: "project-1",
  workflowId: "workflow-1",
  workflowName: "OCR 1",
  status: "completed",
  startedAt: "2026-07-20T08:48:22Z",
  completedAt: "2026-07-20T08:49:22Z",
  duration: 55,
  documentCount: 1,
  passRate: 100,
};

const historicalResult: RunResult = {
  id: "result-history",
  runId: historicalRun.id,
  documentId: "document-1",
  documentName: "one.pdf",
  status: "pass",
  executionStatus: "completed",
  hasGroundTruth: true,
  acceptedAsGT: false,
};

const missingGroundTruthResult: RunResult = {
  ...historicalResult,
  id: "result-no-gt",
  documentId: "document-no-gt",
  documentName: "missing.pdf",
  status: "no_gt",
  hasGroundTruth: false,
};

function createProps(
  overrides: Partial<ComponentProps<typeof RunsView>> = {},
): ComponentProps<typeof RunsView> {
  return {
    activeRunId: null,
    navigate: vi.fn(),
    onAcceptAsGT: vi.fn(),
    onCloseRunDocument: vi.fn(),
    onOpenRun: vi.fn(),
    onRejectResult: vi.fn(),
    onResultComparison: vi.fn(),
    onSelectRunId: vi.fn(),
    onSelectRunDocument: vi.fn(),
    projectId: "project-1",
    runError: null,
    runResults: [],
    runStatus: "idle",
    selectedRunId: null,
    selectedRunDocument: null,
    ...overrides,
  };
}

function renderView(props: ComponentProps<typeof RunsView>) {
  return render(
    <MemoryRouter>
      <RunsView {...props} />
    </MemoryRouter>,
  );
}

describe("RunsView historical run details", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useProjectRuns).mockReturnValue({
      items: [historicalRun],
      loading: false,
      error: null,
      getRunDetail: vi.fn(),
    });
    vi.mocked(compareResult).mockResolvedValue({
      result_id: historicalResult.id,
      document_id: historicalResult.documentId,
      comparison_status: "mismatched",
      diff_mode: "text",
      expected_content: "expected",
      actual_content: "actual",
      diff_fields: [],
    });
  });

  it("renders the run list", () => {
    renderView(createProps());
    expect(screen.getByTestId(`run-row-${historicalRun.id}`)).toBeInTheDocument();
  });

  it("loads a selected historical run and replaces the spinner with its results", () => {
    const onOpenRun = vi.fn();
    const initialProps = createProps({ onOpenRun });
    const view = renderView(initialProps);

    fireEvent.click(screen.getByTestId(`run-row-${historicalRun.id}`));

    expect(onOpenRun).toHaveBeenCalledWith(historicalRun.id);
    expect(initialProps.onSelectRunId).toHaveBeenCalledWith(historicalRun.id);
    view.rerender(
      <MemoryRouter>
        <RunsView {...initialProps} selectedRunId={historicalRun.id} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("run-results-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("run-detail-summary")).not.toBeInTheDocument();
    expect(screen.queryByText("No results for this run.")).not.toBeInTheDocument();

    view.rerender(
      <MemoryRouter>
        <RunsView
          {...initialProps}
          activeRunId={historicalRun.id}
          runResults={[historicalResult]}
          runStatus="completed"
          selectedRunId={historicalRun.id}
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("run-detail-summary")).toHaveTextContent("Total1");
    expect(screen.getByText("one.pdf")).toBeInTheDocument();
  });

  it("separates ground-truth availability from review and counts No GT", () => {
    const props = createProps({
      activeRunId: historicalRun.id,
      runResults: [historicalResult, missingGroundTruthResult],
      runStatus: "completed",
      selectedRunId: historicalRun.id,
    });
    renderView(props);

    expect(screen.getByRole("columnheader", { name: "Ground Truth" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByTestId("run-detail-summary")).toHaveTextContent("Pass1");
    expect(screen.getByTestId("run-detail-summary")).toHaveTextContent("No GT1");
    expect(screen.getByTestId(`result-row-${historicalResult.id}`)).toHaveTextContent("Available");
    expect(screen.getByTestId(`result-row-${historicalResult.id}`)).toHaveTextContent("Unreviewed");
    expect(screen.getByTestId(`result-row-${missingGroundTruthResult.id}`)).toHaveTextContent("No GT");
    expect(screen.getByTestId(`result-row-${missingGroundTruthResult.id}`)).toHaveTextContent("Missing");
  });

  it("shows an inline error and retries the selected run", () => {
    const onOpenRun = vi.fn();
    const initialProps = createProps({ onOpenRun });
    const view = renderView(initialProps);
    fireEvent.click(screen.getByTestId(`run-row-${historicalRun.id}`));

    view.rerender(
      <MemoryRouter>
        <RunsView
          {...initialProps}
          activeRunId={historicalRun.id}
          runError="Results request failed"
          runStatus="failed"
          selectedRunId={historicalRun.id}
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("run-results-error")).toHaveTextContent(
      "Results request failed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onOpenRun).toHaveBeenCalledTimes(2);
  });

  it("uses the selected historical run for compare and review actions", async () => {
    const onAcceptAsGT = vi.fn();
    const onRejectResult = vi.fn();
    const onResultComparison = vi.fn();
    const onSelectRunDocument = vi.fn();
    const props = createProps({
      activeRunId: historicalRun.id,
      onAcceptAsGT,
      onRejectResult,
      onResultComparison,
      onSelectRunDocument,
      runResults: [historicalResult],
      runStatus: "completed",
    });
    const view = renderView(props);

    fireEvent.click(screen.getByTestId(`run-row-${historicalRun.id}`));
    view.rerender(
      <MemoryRouter>
        <RunsView {...props} selectedRunId={historicalRun.id} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId(`result-row-${historicalResult.id}`));
    expect(onSelectRunDocument).toHaveBeenCalledWith(historicalResult);

    view.rerender(
      <MemoryRouter>
        <RunsView
          {...props}
          selectedRunDocument={historicalResult}
          selectedRunId={historicalRun.id}
        />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(compareResult).toHaveBeenCalledWith(
        historicalRun.id,
        historicalResult.id,
      );
      expect(onResultComparison).toHaveBeenCalledWith(
        historicalResult.id,
        "mismatched",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "Accept test" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject test" }));
    expect(onAcceptAsGT).toHaveBeenCalledWith(historicalResult.documentId);
    expect(onRejectResult).toHaveBeenCalledWith(historicalResult.documentId);
  });
});
