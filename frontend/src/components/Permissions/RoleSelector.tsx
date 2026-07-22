import type { WorkspaceRole, WorkspaceRoleDescriptor } from "@/types/workspace";
import { useTranslation } from "react-i18next";

export interface RoleSelectorProps {
  value?: WorkspaceRole;
  roles: WorkspaceRoleDescriptor[];
  disabledRoles?: WorkspaceRole[];
  onChange?: (role: WorkspaceRole) => void;
}

export function RoleSelector({ value, roles, disabledRoles = [], onChange }: RoleSelectorProps) {
  const { t } = useTranslation("workspaces");
  return (
    <div aria-label={t("roleSelector")} className="workspace-role-selector" role="group">
      {roles.map((descriptor) => {
        const disabled = disabledRoles.includes(descriptor.role);
        const label = t(descriptor.role, { defaultValue: descriptor.label });
        const summary = t(`roleSummaries.${descriptor.role}`, { defaultValue: descriptor.summary });
        return (
          <button
            aria-pressed={descriptor.role === value}
            className="workspace-role-chip"
            disabled={disabled}
            key={descriptor.role}
            onClick={() => onChange?.(descriptor.role)}
            title={disabled ? t("roleCannotAssign", { role: label }) : summary}
            type="button"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
