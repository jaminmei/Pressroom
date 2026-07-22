import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApiUsageTab from "@/features/api-access/components/ApiUsageTab";
import {
  getWorkflowApiUsageSummary,
  listWorkflowApiUsageRuns,
} from "@/services/apiAccessApi";

vi.mock("@/services/apiAccessApi", () => ({
  getWorkflowApiUsageSummary: vi.fn(),
  listWorkflowApiUsageRuns: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-probe">{location.pathname}{location.search}</span>;
}

const summary = {
  range: "7d",
  calls: 3,
  success_rate: 0.6667,
  avg_response_time_ms: 1250,
  p95_response_time_ms: 2100,
  failures: 1,
  storage_used_bytes: 2048,
  storage_limit_bytes: 52_428_800,
  storage_over_limit: false,
  trend: [
    { date: "2026-07-01", calls: 0, failures: 0, avg_response_time_ms: 0 },
    { date: "2026-07-02", calls: 1, failures: 0, avg_response_time_ms: 900 },
    { date: "2026-07-03", calls: 2, failures: 1, avg_response_time_ms: 1500 },
  ],
};

const runsResponse = {
  data: [
    {
      id: "api_inv_1",
      workflow_id: "wf_usage",
      workflow_run_id: "task_abc",
      api_key_id: "key_1",
      api_key_prefix: "dca_prod",
      api_key_description: "Prod key",
      endpoint_kind: "file_upload",
      http_status: 200,
      workflow_status: "succeeded",
      response_time_ms: 940,
      input_metadata: {
        mode: "upload",
        file: {
          source_kind: "upload",
          filename: "invoice.pdf",
          size_bytes: 1024,
          mime_type: "application/pdf",
        },
      },
      error: null,
      storage_bytes: 1024,
      created_at: "2026-07-03T10:00:00Z",
      finished_at: "2026-07-03T10:00:01Z",
      result_preview: "ok",
    },
  ],
  meta: { total: 1, page: 1, limit: 20 },
};

function renderTab() {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={["/access"]}>
        <Routes>
          <Route
            element={
              <>
                <ApiUsageTab
                  keys={[{ id: "key_1", key_prefix: "dca_prod", workflow_id: "wf_usage", is_active: true, description: "Prod key" }]}
                  workflowId="wf_usage"
                />
                <LocationProbe />
              </>
            }
            path="/access"
          />
          <Route element={<LocationProbe />} path="/workflows/:workflowId" />
        </Routes>
      </MemoryRouter>
    </AntApp>,
  );
}

describe("ApiUsageTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getWorkflowApiUsageSummary).mockResolvedValue(summary as never);
    vi.mocked(listWorkflowApiUsageRuns).mockResolvedValue(runsResponse as never);
  });

  it("renders summary, run rows, and opens the read-only trace route", async () => {
    renderTab();

    expect(await screen.findByText("Usage")).toBeInTheDocument();
    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText("File upload")).toBeInTheDocument();
    expect(screen.getByText(/upload: invoice.pdf/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open trace/i }));

    await waitFor(() => {
      expect(screen.getByTestId("location-probe")).toHaveTextContent(
        "/workflows/wf_usage?traceRunId=task_abc&from=api-usage",
      );
    });
  });
});
