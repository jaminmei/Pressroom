import "@testing-library/jest-dom/vitest";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunWorkflowPage from "@/features/projects/components/RunWorkflowPage";
import { useProjectDocuments } from "@/features/projects/hooks/useProjectDocuments";
import { useRunWorkflowConfig } from "@/features/projects/hooks/useRunWorkflowConfig";
import { getProject } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { ProjectDocument } from "@/types/project";

vi.mock("@/features/projects/hooks/useProjectDocuments", () => ({
  useProjectDocuments: vi.fn(),
}));

vi.mock("@/features/projects/hooks/useRunWorkflowConfig", () => ({
  useRunWorkflowConfig: vi.fn(),
}));

vi.mock("@/services/projectApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/projectApi")>("@/services/projectApi");
  return { ...actual, getProject: vi.fn() };
});

vi.mock("@/features/projects/components/DocumentThumbnail", () => ({
  default: ({
    documentId,
    onPreview,
  }: {
    documentId: string;
    onPreview?: () => void;
  }) => (
    <span
      data-interactive={onPreview ? "true" : "false"}
      data-testid={`static-thumbnail-${documentId}`}
    />
  ),
}));

const documents: ProjectDocument[] = [
  {
    id: "doc-1",
    projectId: "project-1",
    filename: "alpha-invoice.jpg",
    type: "image/jpeg",
    size: 1024,
    uploadedAt: "2026-07-20T00:00:00Z",
    gtStatus: "none",
  },
  {
    id: "doc-2",
    projectId: "project-1",
    filename: "beta-report.pdf",
    type: "application/pdf",
    size: 2048,
    uploadedAt: "2026-07-20T00:00:00Z",
    gtStatus: "none",
  },
];

const startRun = vi.fn();

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location-probe">
      {location.pathname}|{JSON.stringify(location.state)}
    </div>
  );
}

function renderPage(selectedDocIds: string[] = []) {
  return render(
    <MemoryRouter
      initialEntries={[{
        pathname: "/database/project-1/run",
        state: { selectedDocIds },
      }]}
    >
      <Routes>
        <Route
          path="/database/:projectId/run"
          element={<><RunWorkflowPage /><LocationProbe /></>}
        />
        <Route path="/database/:projectId" element={<LocationProbe />} />
        <Route path="/" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function chooseWorkflow() {
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText("OCR Workflow"));
}

describe("RunWorkflowPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    startRun.mockResolvedValue("run-123");
    vi.mocked(getProject).mockResolvedValue({
      id: "project-1",
      name: "Invoice Dataset",
      documentCount: 2,
      lastUpdated: "2026-07-20T00:00:00Z",
      createdAt: "2026-07-20T00:00:00Z",
    });
    vi.mocked(useProjectDocuments).mockReturnValue({
      documents,
      loading: false,
      error: null,
      uploadDocuments: vi.fn(),
      deleteDocument: vi.fn(),
    });
    vi.mocked(useRunWorkflowConfig).mockReturnValue({
      workflows: [{ id: "workflow-1", name: "OCR Workflow", description: "Extract invoice text." }],
      loading: false,
      error: null,
      selectedWorkflowId: null,
      selectedDocuments: [],
      setSelectedWorkflow: vi.fn(),
      setSelectedDocuments: vi.fn(),
      startRun,
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "owner",
        isDefault: true,
        capabilities: ["database.view", "run.view", "run.create"],
      },
      contextGeneration: 1,
      capabilities: ["database.view", "run.view", "run.create"],
    });
  });

  it("keeps the full document list visible and initializes preselected rows", async () => {
    renderPage(["doc-1"]);

    await screen.findByTestId("rwp-config-phase");
    expect(screen.getByTestId("breadcrumb-project-name")).toHaveTextContent("Invoice Dataset");
    expect(screen.getByTestId("breadcrumb-tail")).toHaveTextContent("Run Workflow");
    expect(screen.getByTestId("ws-nav-runs")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("alpha-invoice.jpg")).toBeInTheDocument();
    expect(screen.getByText("beta-report.pdf")).toBeInTheDocument();
    expect(screen.getByTestId("rwp-doc-checkbox-doc-1")).toBeChecked();
    expect(screen.getByTestId("rwp-doc-checkbox-doc-2")).not.toBeChecked();
    expect(screen.getByTestId("rwp-selected-count")).toHaveTextContent("1 selected");
    expect(screen.getByTestId("static-thumbnail-doc-1")).toHaveAttribute("data-interactive", "false");
  });

  it("searches, selects all visible documents, and clears the complete selection", async () => {
    renderPage(["doc-1"]);
    await screen.findByTestId("rwp-config-phase");

    fireEvent.change(screen.getByTestId("rwp-document-search"), { target: { value: "beta" } });
    expect(screen.queryByText("alpha-invoice.jpg")).not.toBeInTheDocument();
    expect(screen.getByText("beta-report.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("rwp-select-all-visible"));
    expect(screen.getByTestId("rwp-selected-count")).toHaveTextContent("2 selected");

    fireEvent.click(screen.getByTestId("rwp-clear-selection"));
    expect(screen.getByTestId("rwp-selected-count")).toHaveTextContent("0 selected");
  });

  it("starts one run and returns to Documents monitoring with the active run id", async () => {
    renderPage(["doc-1"]);
    await screen.findByTestId("rwp-config-phase");
    await chooseWorkflow();

    expect(screen.getByTestId("rwp-workflow-description")).toHaveTextContent(
      "Extract invoice text.",
    );
    fireEvent.click(screen.getByTestId("rwp-start-run-button"));

    await waitFor(() => {
      expect(startRun).toHaveBeenCalledWith("workflow-1", ["doc-1"], undefined);
      expect(screen.getByTestId("location-probe")).toHaveTextContent(
        '/database/project-1|{"activeRunId":"run-123"}',
      );
    });
  });

  it("keeps the form selections when starting a run fails", async () => {
    startRun.mockRejectedValueOnce(new Error("Run service unavailable"));
    renderPage(["doc-1"]);
    await screen.findByTestId("rwp-config-phase");
    await chooseWorkflow();

    fireEvent.click(screen.getByTestId("rwp-start-run-button"));

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("rwp-start-run-button")).toBeEnabled());
    expect(screen.getByTestId("rwp-selected-count")).toHaveTextContent("1 selected");
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/database/project-1/run");
  });

  it("disables repeat submission while a run is being created", async () => {
    let resolveRun: ((runId: string) => void) | undefined;
    startRun.mockReturnValueOnce(new Promise<string>((resolve) => { resolveRun = resolve; }));
    renderPage(["doc-1"]);
    await screen.findByTestId("rwp-config-phase");
    await chooseWorkflow();

    fireEvent.click(screen.getByTestId("rwp-start-run-button"));

    expect(screen.getByTestId("rwp-start-run-button")).toBeDisabled();
    expect(screen.getByTestId("rwp-run-name-input")).toBeDisabled();
    expect(startRun).toHaveBeenCalledTimes(1);

    await act(async () => { resolveRun?.("run-pending"); });
    await waitFor(() => {
      expect(screen.getByTestId("location-probe")).toHaveTextContent("run-pending");
    });
  });

  it("keeps selection controls disabled without run.create permission", async () => {
    useWorkspaceStore.setState({
      capabilities: ["database.view", "run.view"],
      currentWorkspace: {
        id: "workspace-1",
        name: "Workspace 1",
        role: "viewer",
        isDefault: true,
        capabilities: ["database.view", "run.view"],
      },
    });
    renderPage(["doc-1"]);

    await screen.findByTestId("rwp-config-phase");
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByTestId("rwp-doc-checkbox-doc-1")).toBeDisabled();
    expect(screen.getByTestId("rwp-start-run-button")).toBeDisabled();
  });

  it("shows independent workflow and document empty/error states", async () => {
    vi.mocked(useRunWorkflowConfig).mockReturnValue({
      workflows: [],
      loading: false,
      error: "workflow request failed",
      selectedWorkflowId: null,
      selectedDocuments: [],
      setSelectedWorkflow: vi.fn(),
      setSelectedDocuments: vi.fn(),
      startRun,
    });
    vi.mocked(useProjectDocuments).mockReturnValue({
      documents: [],
      loading: false,
      error: null,
      uploadDocuments: vi.fn(),
      deleteDocument: vi.fn(),
    });

    renderPage();

    expect(await screen.findByTestId("rwp-workflows-error")).toBeInTheDocument();
    expect(screen.getByTestId("rwp-documents-empty")).toHaveTextContent("No documents available");
    expect(screen.getByTestId("rwp-start-run-button")).toBeDisabled();
  });
});
