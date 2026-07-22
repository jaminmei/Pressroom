import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvaluationStatusBadge } from "@/features/projects/components/EvaluationStatusBadge";
import {
  EVALUATION_RESULT_STATUS_LABELS,
  EVALUATION_RUN_STATUS_LABELS,
  getEvaluationStatusDescriptor,
} from "@/features/projects/evaluationStatusLabels";

describe("evaluation status labels", () => {
  it("maps every run and result status to the specified label and color", () => {
    expect(EVALUATION_RUN_STATUS_LABELS).toEqual({
      pending: { color: "default", label: "Pending" },
      running: { color: "blue", label: "Running" },
      completed: { color: "green", label: "Completed" },
      partial_completed: { color: "orange", label: "Partially completed" },
      failed: { color: "red", label: "Failed" },
      cancelled: { color: "default", label: "Cancelled" },
    });
    expect(EVALUATION_RESULT_STATUS_LABELS).toEqual({
      queued: { color: "default", label: "Queued" },
      running: { color: "blue", label: "Running" },
      completed: { color: "green", label: "Completed" },
      failed: { color: "red", label: "Failed" },
      skipped: { color: "default", label: "Skipped" },
    });
  });

  it("renders localized labels and falls back to the unknown status", () => {
    const { rerender } = render(<EvaluationStatusBadge status="partial_completed" />);
    expect(screen.getByText("Partially completed")).toHaveClass("ant-tag-orange");

    rerender(<EvaluationStatusBadge status="unrecognized" />);
    expect(screen.getByText("unrecognized")).toBeInTheDocument();
    expect(getEvaluationStatusDescriptor("unrecognized")).toEqual({
      color: "default",
      label: "unrecognized",
    });
  });
});
