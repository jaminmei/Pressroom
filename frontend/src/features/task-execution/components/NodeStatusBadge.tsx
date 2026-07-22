import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";

import type { TaskNodeVisualStatus } from "@/features/task-execution/store";

interface NodeStatusBadgeProps {
  status?: TaskNodeVisualStatus;
  errorMessage?: string;
}

function NodeStatusGlyph({ status }: { status: TaskNodeVisualStatus }) {
  const commonProps = {
    "aria-hidden": true,
    className: "node-status-glyph",
    focusable: "false" as const,
    viewBox: "0 0 20 20"
  };

  switch (status) {
    case "completed":
      return (
        <svg {...commonProps}>
          <path className="node-status-check" d="m5.2 10.2 3.1 3.1 6.6-6.7" />
        </svg>
      );
    case "running":
      return (
        <svg {...commonProps}>
          <circle className="node-status-spinner-track" cx="10" cy="10" r="6.5" />
          <circle className="node-status-spinner-head" cx="10" cy="10" r="6.5" />
        </svg>
      );
    case "pending":
      return (
        <svg {...commonProps}>
          <circle className="node-status-dot" cx="5" cy="10" r="1.25" />
          <circle className="node-status-dot" cx="10" cy="10" r="1.25" />
          <circle className="node-status-dot" cx="15" cy="10" r="1.25" />
        </svg>
      );
    case "failed":
      return (
        <svg {...commonProps}>
          <path d="m6.2 6.2 7.6 7.6M13.8 6.2l-7.6 7.6" />
        </svg>
      );
    case "awaiting_input":
    case "awaiting_user_input":
      return (
        <svg {...commonProps}>
          <path d="M10 4.8v6.2" />
          <circle className="node-status-dot" cx="10" cy="14.5" r="1.1" />
        </svg>
      );
    case "skipped":
      return (
        <svg {...commonProps}>
          <path d="m4.8 6 4 4-4 4M10.8 6l4 4-4 4" />
        </svg>
      );
    case "cancelled":
      return (
        <svg {...commonProps}>
          <circle cx="10" cy="10" r="6.4" />
          <path d="m5.5 14.5 9-9" />
        </svg>
      );
    default:
      return (
        <svg {...commonProps}>
          <circle cx="10" cy="10" r="6.4" />
        </svg>
      );
  }
}

export default function NodeStatusBadge({ status = "idle", errorMessage }: NodeStatusBadgeProps) {
  const { t } = useTranslation("common");
  const statusLabel = t(`statuses.${status}`, { defaultValue: status });
  const tooltip = status === "failed" && errorMessage ? errorMessage : statusLabel;

  const badge = (
    <span
      aria-label={t("nodeStatus", { status: statusLabel })}
      className={`node-status-badge node-status-${status}${status === "running" ? " node-status-animated" : ""}`}
      data-testid={`node-status-${status}`}
    >
      <NodeStatusGlyph status={status} />
    </span>
  );

  return <Tooltip title={tooltip}>{badge}</Tooltip>;
}
