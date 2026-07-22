import { Alert, Result } from "antd";
import { useTranslation } from "react-i18next";

import { usePermission } from "@/hooks/usePermission";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useWorkspaceAudit } from "../hooks/useWorkspaceAudit";

export default function WorkspaceAuditPage() {
  const { t } = useTranslation("workspaces");
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const { can } = usePermission();
  const canViewAudit = can("audit.view");
  useWorkspaceAudit(
    currentWorkspace?.id || "",
    canViewAudit
  );

  if (!currentWorkspace) return null;

  if (!canViewAudit) {
    return (
      <section className="workspace-panel workspace-audit-panel">
        <Result
          data-testid="workspace-audit-denied"
          status="403"
          subTitle={t("auditDenied")}
          title={t("accessDenied")}
        />
      </section>
    );
  }

  return (
    <div className="workspace-page-stack workspace-audit-page">
      <section className="workspace-panel workspace-audit-panel" aria-labelledby="workspace-audit-title">
        <div className="workspace-panel-head">
          <div>
            <h2 id="workspace-audit-title">{t("auditComingSoon")}</h2>
            <p>{t("auditNotPersisted")}</p>
          </div>
        </div>

        <div className="workspace-audit-body">
          <Alert
            data-testid="audit-coming-soon-banner"
            description={t("auditIncomplete")}
            message={t("comingSoon")}
            showIcon
            type="info"
          />
        </div>
      </section>
    </div>
  );
}
