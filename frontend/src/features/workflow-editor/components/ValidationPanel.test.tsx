import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ValidationPanel from "@/features/workflow-editor/components/ValidationPanel";
import type { WorkflowValidationIssue } from "@/features/workflow-editor/utils/workflowValidator";

const blockingErrors: WorkflowValidationIssue[] = [
  {
    code: "MISSING_REQUIRED_CONFIG",
    message: "input_1 缺少檔案",
    nodeId: "input_1",
    severity: "blocking"
  }
];

const warnings: WorkflowValidationIssue[] = [
  {
    code: "WORKFLOW_ORPHAN_NODE",
    message: "engine_2 是孤立節點",
    nodeId: "engine_2",
    severity: "warning"
  }
];

describe("ValidationPanel", () => {
  it("renders grouped blocking and warning issues", () => {
    render(
      <ValidationPanel
        blockingErrors={blockingErrors}
        isOpen
        onClose={vi.fn()}
        onSelectIssue={vi.fn()}
        warnings={warnings}
      />
    );

    expect(screen.getByText("Blocking")).toBeInTheDocument();
    expect(screen.getByText("Warnings")).toBeInTheDocument();
    expect(screen.getByText("input_1 缺少檔案")).toBeInTheDocument();
    expect(screen.getByText("engine_2 是孤立節點")).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    const { container } = render(
      <ValidationPanel
        blockingErrors={blockingErrors}
        isOpen={false}
        onClose={vi.fn()}
        onSelectIssue={vi.fn()}
        warnings={warnings}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("calls onSelectIssue when issue is clicked", () => {
    const onSelectIssue = vi.fn();
    render(
      <ValidationPanel
        blockingErrors={blockingErrors}
        isOpen
        onClose={vi.fn()}
        onSelectIssue={onSelectIssue}
        warnings={warnings}
      />
    );

    fireEvent.click(screen.getByText("input_1 缺少檔案"));
    expect(onSelectIssue).toHaveBeenCalledWith(blockingErrors[0]);
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <ValidationPanel
        blockingErrors={blockingErrors}
        isOpen
        onClose={onClose}
        onSelectIssue={vi.fn()}
        warnings={warnings}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
