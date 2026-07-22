import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PreRunValidationDialog from "@/features/workflow-editor/components/PreRunValidationDialog";
import type { PreRunValidationResult } from "@/features/workflow-editor/components/PreRunValidationDialog";

function makeStaticErrorResult(): PreRunValidationResult {
  return {
    static: {
      valid: false,
      errors: [
        { code: "MISSING_FILE", message: "File is required", severity: "error", node_id: "input_1" },
      ],
      warnings: [],
    },
    dynamic: { warnings: [] },
  };
}

function makeDynamicWarningResult(): PreRunValidationResult {
  return {
    static: { valid: true, errors: [], warnings: [] },
    dynamic: {
      warnings: [
        {
          code: "MODEL_NO_VISION",
          severity: "warning",
          node_id: "engine_1",
          message: "Model does not support vision input",
          model: "gpt-4",
          edge_ids: ["e-1"],
        },
      ],
    },
  };
}

function makeDynamicInfoResult(): PreRunValidationResult {
  return {
    static: { valid: true, errors: [], warnings: [] },
    dynamic: {
      warnings: [
        {
          code: "MODEL_NOT_SELECTED",
          severity: "info",
          node_id: "engine_1",
          message: "No model selected yet",
          model: null,
          edge_ids: [],
        },
      ],
    },
  };
}

describe("PreRunValidationDialog", () => {
  it("renders nothing when validationResult is null", () => {
    const { container } = render(
      <PreRunValidationDialog
        open={true}
        validationResult={null}
        onProceed={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("shows error dialog with OK button for static errors", () => {
    render(
      <PreRunValidationDialog
        open={true}
        validationResult={makeStaticErrorResult()}
        onProceed={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText("Validation Errors")).toBeInTheDocument();
    expect(screen.getByText("File is required")).toBeInTheDocument();
    expect(screen.getAllByText("Close").length).toBeGreaterThan(0);
    expect(screen.queryByText("Run Anyway")).not.toBeInTheDocument();
  });

  it("shows warning dialog with Run Anyway and Cancel for dynamic warnings", () => {
    render(
      <PreRunValidationDialog
        open={true}
        validationResult={makeDynamicWarningResult()}
        onProceed={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText("Validation Warnings")).toBeInTheDocument();
    expect(screen.getByText("Model does not support vision input")).toBeInTheDocument();
    expect(screen.getByText("Run Anyway")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("shows info dialog with Continue and Cancel for info-only", () => {
    render(
      <PreRunValidationDialog
        open={true}
        validationResult={makeDynamicInfoResult()}
        onProceed={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText("Advisory Notices")).toBeInTheDocument();
    expect(screen.getByText("No model selected yet")).toBeInTheDocument();
    expect(screen.getByText("Continue")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("calls onProceed when Run Anyway clicked", () => {
    const onProceed = vi.fn();
    render(
      <PreRunValidationDialog
        open={true}
        validationResult={makeDynamicWarningResult()}
        onProceed={onProceed}
        onCancel={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Run Anyway"));

    expect(onProceed).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when Cancel clicked", () => {
    const onCancel = vi.fn();
    render(
      <PreRunValidationDialog
        open={true}
        validationResult={makeDynamicWarningResult()}
        onProceed={vi.fn()}
        onCancel={onCancel}
      />
    );

    fireEvent.click(screen.getByText("Cancel"));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
