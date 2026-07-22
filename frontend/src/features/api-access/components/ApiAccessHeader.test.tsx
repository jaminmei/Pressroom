import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";

import ApiAccessHeader from "@/features/api-access/components/ApiAccessHeader";
import type { WorkflowDetailResponse } from "@/services/workflowApi";

const base: WorkflowDetailResponse = {
  id: "wf_invoice_extract",
  name: "Invoice Extraction",
  definition: { nodes: [], connections: [] },
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-29T00:00:00Z",
  published_version: 3,
  latest_version: 4,
};

describe("ApiAccessHeader", () => {
  it("renders workflow name, published version tag, latest version, and workflow id", () => {
    render(<ApiAccessHeader workflow={base} />);

    expect(screen.getByText("Invoice Extraction")).toBeInTheDocument();
    expect(screen.getByText(/Published v3/i)).toBeInTheDocument();
    expect(screen.getByText(/Latest v4/i)).toBeInTheDocument();
    expect(screen.getByText("wf_invoice_extract")).toBeInTheDocument();
  });

  it("falls back to Untitled workflow when name is missing", () => {
    render(<ApiAccessHeader workflow={{ ...base, name: undefined }} />);

    expect(screen.getByText(/Untitled workflow/i)).toBeInTheDocument();
  });
});
