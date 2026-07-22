import type { TagProps } from "antd";

import type {
  EvaluationResultStatus,
  EvaluationRunStatus,
} from "@/services/evaluationRunApi";

export interface EvaluationStatusDescriptor {
  readonly color: TagProps["color"];
  readonly label: string;
}

export const EVALUATION_RUN_STATUS_LABELS = {
  pending: { color: "default", label: "Pending" },
  running: { color: "blue", label: "Running" },
  completed: { color: "green", label: "Completed" },
  partial_completed: { color: "orange", label: "Partially completed" },
  failed: { color: "red", label: "Failed" },
  cancelled: { color: "default", label: "Cancelled" },
} satisfies Record<EvaluationRunStatus, EvaluationStatusDescriptor>;

export const EVALUATION_RESULT_STATUS_LABELS = {
  queued: { color: "default", label: "Queued" },
  running: { color: "blue", label: "Running" },
  completed: { color: "green", label: "Completed" },
  failed: { color: "red", label: "Failed" },
  skipped: { color: "default", label: "Skipped" },
} satisfies Record<EvaluationResultStatus, EvaluationStatusDescriptor>;

export function getEvaluationStatusDescriptor(status: string): EvaluationStatusDescriptor {
  const labels: Readonly<Record<string, EvaluationStatusDescriptor>> = EVALUATION_RUN_STATUS_LABELS;
  const resultLabels: Readonly<Record<string, EvaluationStatusDescriptor>> = EVALUATION_RESULT_STATUS_LABELS;
  return labels[status]
    ?? resultLabels[status]
    ?? { color: "default", label: status };
}
