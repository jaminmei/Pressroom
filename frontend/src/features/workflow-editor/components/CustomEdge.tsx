import type { CSSProperties } from "react";

import type { TaskNodeVisualStatus } from "@/features/task-execution/store";

export type WorkflowEdgeExecutionStatus =
  | "idle"
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_input"
  | "skipped"
  | "cancelled";

export interface CustomEdgeStyleState {
  isTypeWarning: boolean;
  executionStatus?: WorkflowEdgeExecutionStatus;
}

export function getCustomEdgeStyle(state: CustomEdgeStyleState): CSSProperties {
  const executionStatus = state.executionStatus ?? "idle";

  if (state.isTypeWarning && (executionStatus === "idle" || executionStatus === "pending")) {
    return {
      stroke: "#d48806",
      strokeDasharray: "6 4",
      strokeWidth: 2
    };
  }

  switch (executionStatus) {
    case "pending":
      return {
        stroke: "#aeb7c6",
        strokeDasharray: undefined,
        strokeWidth: 2
      };
    case "running":
      return {
        stroke: "#1677ff",
        strokeDasharray: "9 7",
        strokeWidth: 3
      };
    case "completed":
      return {
        stroke: "#22a06b",
        strokeDasharray: undefined,
        strokeWidth: 2.5
      };
    case "failed":
      return {
        stroke: "#e5484d",
        strokeDasharray: undefined,
        strokeWidth: 3
      };
    case "awaiting_input":
      return {
        stroke: "#d48806",
        strokeDasharray: "6 4",
        strokeWidth: 2.5
      };
    case "skipped":
    case "cancelled":
      return {
        stroke: "#98a2b3",
        strokeDasharray: "4 5",
        strokeWidth: 2
      };
    default:
      return {
        stroke: "#7132f5",
        strokeDasharray: undefined,
        strokeWidth: 2
      };
  }
}

export function resolveWorkflowEdgeExecutionStatus(
  sourceStatus?: TaskNodeVisualStatus,
  targetStatus?: TaskNodeVisualStatus
): WorkflowEdgeExecutionStatus {
  if (targetStatus === "failed" || sourceStatus === "failed") return "failed";
  if (targetStatus === "cancelled" || sourceStatus === "cancelled") return "cancelled";

  switch (targetStatus) {
    case "running":
      return "running";
    case "completed":
      return "completed";
    case "awaiting_input":
    case "awaiting_user_input":
      return "awaiting_input";
    case "skipped":
      return "skipped";
    case "pending":
      return "pending";
    default:
      return "idle";
  }
}
