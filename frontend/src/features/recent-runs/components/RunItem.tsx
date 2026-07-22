import { createElement } from "react";

import { getStatusIcon } from "@/components/Icons/IconRegistry";
import type { TaskHistoryItem } from "@/types/task";

interface RunItemProps {
  item: TaskHistoryItem;
  onClick: () => void;
}

function formatRelativeTime(isoTime: string): string {
  const diffMs = Date.now() - new Date(isoTime).getTime();
  const diffMinutes = Math.max(1, Math.floor(diffMs / 60000));

  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

export default function RunItem({ item, onClick }: RunItemProps) {
  const displayName = item.run_name ?? item.workflow_name ?? item.task_id.slice(5, 13);
  const displayId = item.run_name ? item.task_id.slice(5, 13) : null;
  const StatusIcon = getStatusIcon(item.status);
  const isAnimated = item.status === "pending" || item.status === "running";

  return (
    <button className="run-item" data-testid="run-item" onClick={onClick} title={item.started_at} type="button">
      <div className="run-item-task-id">{displayName}</div>
      <div className="run-item-workflow">{displayId ?? item.task_id.slice(5, 13)}</div>
      <div className="run-item-meta">
        <span className={isAnimated ? "node-status-spin" : ""}>{createElement(StatusIcon, { size: 18 })}</span>
        <span>{item.status}</span>
        <span>{formatRelativeTime(item.started_at)}</span>
      </div>
    </button>
  );
}
