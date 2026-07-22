import {
  ApiOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  TeamOutlined,
  UserAddOutlined
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { RoleBadge } from "@/components/Permissions/RoleBadge";
import { useWorkspaceStore } from "@/stores/workspaceStore";

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "WS";
  return parts.slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

export default function WorkspaceOverviewPage() {
  const { t } = useTranslation("workspaces");
  const navigate = useNavigate();
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);

  if (!currentWorkspace) return null;

  const metrics = [
    { label: t("members"), value: currentWorkspace.memberCount ?? "—", icon: <TeamOutlined /> },
    { label: t("workflows"), value: currentWorkspace.workflowCount ?? "—", icon: <FolderOpenOutlined /> },
    { label: t("databases"), value: currentWorkspace.databaseCount ?? "—", icon: <DatabaseOutlined /> },
    { label: t("providers"), value: currentWorkspace.providerCount ?? "—", icon: <ApiOutlined /> }
  ];

  return (
    <div className="workspace-page-stack workspace-overview-page">
      <section className="workspace-hero-panel" aria-labelledby="workspace-overview-title">
        <span className="workspace-hero-mark" aria-hidden>
          {getInitials(currentWorkspace.name)}
        </span>
        <div className="workspace-hero-copy">
          <div className="workspace-hero-title-row">
            <h2 id="workspace-overview-title">{currentWorkspace.name}</h2>
            <RoleBadge role={currentWorkspace.role} />
          </div>
          <p>
            {currentWorkspace.description || t("defaultDescription")}
          </p>
          <span className="workspace-hero-meta">
            {t("yourRole", { role: t(currentWorkspace.role) })}
          </span>
        </div>
      </section>

      <section className="workspace-metrics-grid" aria-label={t("workspaceSummary")}>
        {metrics.map((metric) => (
          <article className="workspace-metric-card" key={metric.label}>
            <span className="workspace-metric-icon" aria-hidden>{metric.icon}</span>
            <div>
              <span className="workspace-metric-label">{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          </article>
        ))}
      </section>

      <section className="workspace-panel workspace-quick-actions" aria-labelledby="workspace-quick-actions-title">
        <div className="workspace-panel-head">
          <div>
            <h2 id="workspace-quick-actions-title">{t("quickActions")}</h2>
            <p>{t("quickActionsDescription")}</p>
          </div>
        </div>
        <div className="workspace-panel-body workspace-action-row">
          <PermissionButton
            capability="workflow.create"
            icon={<FolderOpenOutlined />}
            onClick={() => navigate("/studio")}
            type="primary"
          >
            {t("newWorkflow")}
          </PermissionButton>
          <PermissionButton
            capability="members.invite"
            icon={<UserAddOutlined />}
            onClick={() => navigate("/settings/workspace/members?action=invite")}
          >
            {t("inviteMember")}
          </PermissionButton>
          <PermissionButton
            capability="provider.manage"
            icon={<ApiOutlined />}
            onClick={() => navigate("/settings/workspace/providers")}
          >
            {t("configureProviders")}
          </PermissionButton>
        </div>
      </section>
    </div>
  );
}
