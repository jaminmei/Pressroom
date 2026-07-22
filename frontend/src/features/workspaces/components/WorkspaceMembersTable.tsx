import { EditOutlined, LockOutlined, MoreOutlined, UserDeleteOutlined } from "@ant-design/icons";
import { Button, Dropdown } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";

import { RoleBadge } from "@/components/Permissions/RoleBadge";
import type { WorkspaceMember } from "@/types/workspace";

export interface WorkspaceMembersTableProps {
  members: WorkspaceMember[];
  loading?: boolean;
  canChangeRole: boolean;
  canRemove: boolean;
  onChangeRole: (member: WorkspaceMember) => void;
  onRemoveMember: (member: WorkspaceMember) => void;
}

function getInitials(member: WorkspaceMember): string {
  const source = member.name?.trim() || member.email.split("@")[0] || "Member";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function getDisplayName(member: WorkspaceMember): string {
  return member.name?.trim() || member.email.split("@")[0] || "Workspace member";
}

export function WorkspaceMembersTable({
  members,
  loading = false,
  canChangeRole,
  canRemove,
  onChangeRole,
  onRemoveMember,
}: WorkspaceMembersTableProps) {
  const { t } = useTranslation(["common", "workspaces"]);
  return (
    <div
      aria-busy={loading}
      aria-label={t("workspaces:membersTable")}
      className={`workspace-member-table ${loading ? "is-loading" : ""}`.trim()}
      data-testid="workspace-members-table"
      role="table"
    >
      <div className="workspace-member-header" role="row">
        <span role="columnheader">{t("workspaces:member")}</span>
        <span role="columnheader">{t("workspaces:role")}</span>
        <span role="columnheader">{t("common:status")}</span>
        <span className="workspace-member-action-heading" role="columnheader">{t("common:actions")}</span>
      </div>

      {members.map((member) => {
        const protectedMember = member.isCurrentUser === true || member.role === "owner";
        const hasActions = !protectedMember && (canChangeRole || canRemove);
        const displayName = getDisplayName(member);
        const menuItems: MenuProps["items"] = [
          {
            key: "change-role",
            icon: <EditOutlined />,
            label: t("workspaces:changeRole"),
            disabled: !canChangeRole
          },
          {
            key: "remove",
            danger: true,
            icon: <UserDeleteOutlined />,
            label: t("workspaces:removeMember"),
            disabled: !canRemove
          }
        ];

        const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
          if (key === "change-role" && canChangeRole) onChangeRole(member);
          if (key === "remove" && canRemove) onRemoveMember(member);
        };

        return (
          <div className="workspace-member-row" key={member.userId} role="row">
            <div className="workspace-member-main" role="cell">
              <span className="workspace-member-avatar" aria-hidden>{getInitials(member)}</span>
              <span className="workspace-member-copy">
                <span className="workspace-member-name">
                  {displayName}
                  {member.isCurrentUser ? <span className="workspace-you-pill">{t("workspaces:you")}</span> : null}
                </span>
                <span className="workspace-member-email">{member.email}</span>
              </span>
            </div>
            <div className="workspace-member-role" data-label={t("workspaces:role")} role="cell">
              <RoleBadge role={member.role} size="sm" />
            </div>
            <div className="workspace-member-status" data-label={t("common:status")} role="cell">
              <span className={`workspace-member-status-pill is-${member.status}`}>
                {t(`common:statuses.${member.status}`, { defaultValue: member.status })}
              </span>
            </div>
            <div className="workspace-member-actions" role="cell">
              {hasActions ? (
                <Dropdown
                  menu={{ items: menuItems, onClick: handleMenuClick }}
                  placement="bottomRight"
                  trigger={["click"]}
                >
                  <Button
                    aria-label={t("workspaces:moreActions", { name: displayName })}
                    className="workspace-member-action"
                    icon={<MoreOutlined />}
                  >
                    {t("workspaces:more")}
                  </Button>
                </Dropdown>
              ) : (
                <span
                  title={protectedMember
                    ? t("workspaces:protectedMember")
                    : t("workspaces:manageDenied")}
                >
                  <Button
                    aria-label={t("workspaces:actionsLocked", { name: displayName })}
                    className="workspace-member-action"
                    disabled
                    icon={<LockOutlined />}
                  >
                    {t("workspaces:locked")}
                  </Button>
                </span>
              )}
            </div>
          </div>
        );
      })}
      {loading ? (
        <div className="workspace-member-loading" role="status">
          {t("workspaces:loadingMembers")}
        </div>
      ) : null}
    </div>
  );
}
