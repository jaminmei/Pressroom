import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WorkflowStudioListItem from "@/features/workflow-studio/components/WorkflowStudioListItem";
import type { WorkflowListItem } from "@/services/workflowApi";

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: () => true,
    explain: () => ({ allowed: true }),
    role: "admin",
  }),
}));

const baseWorkflow: WorkflowListItem = {
  id: "wf_x",
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-29T00:00:00Z",
};

describe("WorkflowStudioListItem — API Access entry", () => {
  it("renders API Access button and Published tag when published_version is set", () => {
    render(
      <WorkflowStudioListItem
        deleting={false}
        hasNewerVersion={false}
        onDelete={vi.fn()}
        onOpen={vi.fn()}
        onOpenApiAccess={vi.fn()}
        onRename={vi.fn()}
        workflow={{ ...baseWorkflow, published_version: 3, latest_version: 4 }}
      />
    );

    expect(screen.getByText("Published v3")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-studio-api-access-wf_x")).toBeEnabled();
  });

  it("disables API Access button and shows no Published tag when published_version is null", () => {
    render(
      <WorkflowStudioListItem
        deleting={false}
        hasNewerVersion={false}
        onDelete={vi.fn()}
        onOpen={vi.fn()}
        onOpenApiAccess={vi.fn()}
        onRename={vi.fn()}
        workflow={{ ...baseWorkflow, published_version: null, latest_version: 2 }}
      />
    );

    expect(screen.queryByText(/Published v/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("workflow-studio-api-access-wf_x")).toBeDisabled();
  });

  it("renders publish guidance tooltip text for unpublished workflows", async () => {
    const { container } = render(
      <WorkflowStudioListItem
        deleting={false}
        hasNewerVersion={false}
        onDelete={vi.fn()}
        onOpen={vi.fn()}
        onOpenApiAccess={vi.fn()}
        onRename={vi.fn()}
        workflow={{ ...baseWorkflow, published_version: null, latest_version: 2 }}
      />
    );

    const tooltipWrapper = container.querySelector(".ant-tooltip-open") ?? container.querySelector("[data-testid='workflow-studio-api-access-wf_x']")?.parentElement;
    fireEvent.mouseEnter(tooltipWrapper as HTMLElement);

    const tooltipText = await screen.findByText("Publish workflow before enabling API access");
    expect(tooltipText).toBeInTheDocument();
  });

  it("calls onOpenApiAccess with the workflow when clicked", () => {
    const onOpenApiAccess = vi.fn();
    render(
      <WorkflowStudioListItem
        deleting={false}
        hasNewerVersion={false}
        onDelete={vi.fn()}
        onOpen={vi.fn()}
        onOpenApiAccess={onOpenApiAccess}
        onRename={vi.fn()}
        workflow={{ ...baseWorkflow, published_version: 1, latest_version: 1 }}
      />
    );

    fireEvent.click(screen.getByTestId("workflow-studio-api-access-wf_x"));

    expect(onOpenApiAccess).toHaveBeenCalledTimes(1);
    expect(onOpenApiAccess.mock.calls[0][0].id).toBe("wf_x");
  });
});
