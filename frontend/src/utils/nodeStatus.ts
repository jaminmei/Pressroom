import type { TaskNodeVisualStatus } from "@/features/task-execution/store";

/**
 * Map a backend node status string to the visual status type used by the UI.
 *
 * Returns `null` for unrecognised status values.
 */
export function mapNodeVisualStatus(status: unknown): TaskNodeVisualStatus | null {
  if (
    status === "pending" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "skipped"
  ) {
    return status;
  }
  if (status === "awaiting_input" || status === "awaiting_user_input") {
    return "awaiting_input";
  }
  return null;
}
