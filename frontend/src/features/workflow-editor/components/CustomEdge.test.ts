import { describe, expect, it } from "vitest";

import {
  getCustomEdgeStyle,
  resolveWorkflowEdgeExecutionStatus
} from "@/features/workflow-editor/components/CustomEdge";

describe("getCustomEdgeStyle", () => {
  it("returns default style for normal edge", () => {
    expect(getCustomEdgeStyle({ isTypeWarning: false })).toEqual({
      stroke: "#7132f5",
      strokeDasharray: undefined,
      strokeWidth: 2
    });
  });

  it("returns warning style for type mismatch edge", () => {
    expect(getCustomEdgeStyle({ isTypeWarning: true })).toEqual({
      stroke: "#d48806",
      strokeDasharray: "6 4",
      strokeWidth: 2
    });
  });

  it.each([
    ["pending", "#aeb7c6", undefined, 2],
    ["running", "#1677ff", "9 7", 3],
    ["completed", "#22a06b", undefined, 2.5],
    ["failed", "#e5484d", undefined, 3],
    ["awaiting_input", "#d48806", "6 4", 2.5],
    ["skipped", "#98a2b3", "4 5", 2]
  ] as const)(
    "returns the %s execution style",
    (executionStatus, stroke, strokeDasharray, strokeWidth) => {
      expect(getCustomEdgeStyle({ isTypeWarning: false, executionStatus })).toEqual({
        stroke,
        strokeDasharray,
        strokeWidth
      });
    }
  );

  it("maps the target node state to the incoming edge and propagates terminal failures", () => {
    expect(resolveWorkflowEdgeExecutionStatus("completed", "running")).toBe("running");
    expect(resolveWorkflowEdgeExecutionStatus("completed", "completed")).toBe("completed");
    expect(resolveWorkflowEdgeExecutionStatus("completed", "awaiting_user_input")).toBe(
      "awaiting_input"
    );
    expect(resolveWorkflowEdgeExecutionStatus("failed", "pending")).toBe("failed");
    expect(resolveWorkflowEdgeExecutionStatus(undefined, undefined)).toBe("idle");
  });
});
