import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowApiAccessPage from "@/features/api-access/components/WorkflowApiAccessPage";
import { listWorkflowApiKeys } from "@/services/apiAccessApi";
import { getWorkflowDetail } from "@/services/workflowApi";

const ORIGIN = "http://localhost:5173";

vi.mock("@/services/workflowApi", () => ({
  getWorkflowDetail: vi.fn(),
}));

vi.mock("@/services/apiAccessApi", () => ({
  listWorkflowApiKeys: vi.fn(),
  issueWorkflowApiKey: vi.fn(),
  revokeWorkflowApiKey: vi.fn(),
  getWorkflowApiUsageSummary: vi.fn(),
  listWorkflowApiUsageRuns: vi.fn(),
  getWorkflowApiUsageTrace: vi.fn(),
}));

const publishedWorkflow = {
  id: "wf_invoice_extract",
  name: "Invoice Extraction",
  definition: { nodes: [], edges: [] },
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-29T00:00:00Z",
  published_version: 3,
  latest_version: 4,
};

const unpublishedWorkflow = { ...publishedWorkflow, published_version: null };

function renderPage(path: string) {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<WorkflowApiAccessPage />} path="workflows/:workflowId/api-access" />
        </Routes>
      </MemoryRouter>
    </AntApp>
  );
}

describe("WorkflowApiAccessPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "location", {
      value: { origin: ORIGIN },
      writable: true,
    });
  });

  it("S1: published workflow renders the full dashboard (header, endpoint, curl, key manager, readiness)", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(publishedWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue({
      data: [{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_invoice_extract", is_active: true, description: "Prod", created_at: "2026-06-01T00:00:00Z" }],
      meta: { total: 1, page: 1, limit: 10 },
    } as never);

    renderPage("/workflows/wf_invoice_extract/api-access");

    await waitFor(() => expect(screen.getByText("Invoice Extraction")).toBeInTheDocument());

    const pageText = screen.getByTestId("api-access-page").textContent ?? "";
    expect(screen.getByText(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`)).toBeInTheDocument();
    expect(screen.getByText(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run/upload`)).toBeInTheDocument();
    expect(pageText).toContain(`${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}`);
    expect(pageText).toContain(`${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}/results`);
    expect(screen.getByText(/curl -X POST/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate/i })).toBeInTheDocument();
    expect(screen.getByText(/saved workflow exists/i)).toBeInTheDocument();
    expect(screen.queryByText(/requires a published workflow/i)).not.toBeInTheDocument();
  });

  it("S2: unpublished workflow renders only the locked state", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(unpublishedWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue({ data: [], meta: { total: 0, page: 1, limit: 10 } } as never);

    renderPage("/workflows/wf_invoice_extract/api-access");

    await waitFor(() => expect(screen.getByText(/requires a published workflow/i)).toBeInTheDocument());

    expect(screen.queryByText(`${ORIGIN}/api/v1/workflows/`)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
  });

  it("S5: shows a spinner while loading", () => {
    vi.mocked(getWorkflowDetail).mockReturnValue(new Promise(() => {})); // never resolves
    vi.mocked(listWorkflowApiKeys).mockResolvedValue({ data: [], meta: { total: 0, page: 1, limit: 10 } } as never);

    renderPage("/workflows/wf_invoice_extract/api-access");

    expect(document.querySelector(".ant-spin-spinning")).not.toBeNull();
  });

  it("S5: shows an error alert when the workflow fails to load", async () => {
    vi.mocked(getWorkflowDetail).mockRejectedValue(new Error("boom"));
    vi.mocked(listWorkflowApiKeys).mockResolvedValue({ data: [], meta: { total: 0, page: 1, limit: 10 } } as never);

    renderPage("/workflows/wf_invoice_extract/api-access");

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
