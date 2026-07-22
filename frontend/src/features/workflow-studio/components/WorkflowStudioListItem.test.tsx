import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowStudioListItem from "./WorkflowStudioListItem";

let currentCaps: string[] = ["workflow.delete", "workflow.edit_draft", "api_key.view"];

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (cap: string) => currentCaps.includes(cap),
    explain: () => "mock reason",
    role: "Admin"
  })
}));

const mockWorkflow = {
  id: "wf_1",
  name: "Test",
  description: "",
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
  published_version: null,
  latest_version: 1,
  definition: { nodes: [], connections: [] }
};

describe("WorkflowStudioListItem", () => {
  beforeEach(() => {
    currentCaps = ["workflow.delete", "workflow.edit_draft", "api_key.view"];
  });

  it("renders active delete button when capability is present", () => {
    render(<WorkflowStudioListItem deleting={false} hasNewerVersion={false} onDelete={vi.fn()} onOpen={vi.fn()} onRename={vi.fn()} workflow={mockWorkflow} />);
    expect(screen.getByRole("button", { name: /delete/i })).not.toBeDisabled();
  });

  it("disables delete button when capability is absent", () => {
    currentCaps = [];
    render(<WorkflowStudioListItem deleting={false} hasNewerVersion={false} onDelete={vi.fn()} onOpen={vi.fn()} onRename={vi.fn()} workflow={mockWorkflow} />);
    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
  });
});
