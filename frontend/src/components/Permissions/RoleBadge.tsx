import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";

import { WORKSPACE_ROLES } from "@/types/workspace";
import type { WorkspaceRole } from "@/types/workspace";

export interface RoleBadgeProps {
  role: WorkspaceRole;
  size?: "sm" | "md";
  showTooltip?: boolean;
}

export function RoleBadge({ role, size = "md", showTooltip = false }: RoleBadgeProps) {
  const { t } = useTranslation("workspaces");
  const descriptor = WORKSPACE_ROLES.find((item) => item.role === role);
  const label = t(role, { defaultValue: descriptor?.label ?? role });
  const summary = t(`roleSummaries.${role}`, { defaultValue: descriptor?.summary ?? "" });
  const badge = (
    <span className="workspace-role-badge" data-size={size}>
      {label}
    </span>
  );

  if (showTooltip && descriptor?.summary) {
    return <Tooltip title={summary}>{badge}</Tooltip>;
  }

  return badge;
}
