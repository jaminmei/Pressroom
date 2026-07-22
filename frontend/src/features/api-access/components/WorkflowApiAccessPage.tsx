import { Alert, Flex, Spin, Tabs } from "antd";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import ApiAccessHeader from "@/features/api-access/components/ApiAccessHeader";
import ApiAccessLockedState from "@/features/api-access/components/ApiAccessLockedState";
import ApiKeyManagerCard from "@/features/api-access/components/ApiKeyManagerCard";
import ApiUsageTab from "@/features/api-access/components/ApiUsageTab";
import InvocationExampleCard from "@/features/api-access/components/InvocationExampleCard";
import PublicEndpointCard from "@/features/api-access/components/PublicEndpointCard";
import RunHistoryCard from "@/features/api-access/components/RunHistoryCard";
import ReadinessCard from "@/features/api-access/components/ReadinessCard";
import { useWorkflowApiAccess } from "@/features/api-access/hooks/useWorkflowApiAccess";
import { usePermission } from "@/hooks/usePermission";

export default function WorkflowApiAccessPage() {
  const { t } = useTranslation(["common", "apiAccess"]);
  const { workflowId } = useParams<{ workflowId: string }>();
  const { can, role } = usePermission();
  const canViewApiKeys = role === null || can("api_key.view");
  const canViewUsage = role === null || can("api_usage.view");
  const access = useWorkflowApiAccess(canViewApiKeys ? workflowId : undefined);

  if (!canViewApiKeys) {
    return (
      <Alert
        data-testid="api-access-forbidden"
        description={t("apiAccess:viewDenied")}
        message={t("apiAccess:forbidden")}
        showIcon
        type="error"
      />
    );
  }

  if (access.loading) {
    return (
      <Flex align="center" data-testid="api-access-loading" gap={12} justify="center" style={{ minHeight: 320 }} vertical>
        <Spin size="large" />
        <span>{t("apiAccess:loadingAccess")}</span>
      </Flex>
    );
  }

  if (access.error) {
    return (
      <Alert
        data-testid="api-access-error"
        description={t("apiAccess:tryOrReturn")}
        message={t("apiAccess:loadAccessFailed")}
        showIcon
        type="error"
      />
    );
  }

  if (!access.workflow || !workflowId) {
    return (
      <Alert
        data-testid="api-access-not-found"
        description={t("apiAccess:workflowNotFoundDescription")}
        message={t("apiAccess:workflowNotFound")}
        showIcon
        type="error"
      />
    );
  }

  if (!access.isPublished) {
    return <ApiAccessLockedState workflowId={workflowId} />;
  }

  const activeKeyCount = access.keys.filter((k) => k.is_active).length;

  return (
    <section className="api-access-dashboard" data-testid="api-access-page">
      <ApiAccessHeader workflow={access.workflow} />

      <Tabs
        className="api-access-tabs"
        defaultActiveKey="setup"
        items={[
          {
            key: "setup",
            label: t("apiAccess:setup"),
            children: (
              <>
                <section className="api-metric-grid" aria-label={t("apiAccess:accessSummary")}>
                  <article className="api-metric-card">
                    <div className="api-metric-label">{t("apiAccess:activeKeys")}</div>
                    <div className="api-metric-value">{activeKeyCount}</div>
                    <div className="api-metric-note">{t("apiAccess:workflowScoped")}</div>
                  </article>
                  <article className="api-metric-card">
                    <div className="api-metric-label">{t("apiAccess:totalKeys")}</div>
                    <div className="api-metric-value">{access.keys.length}</div>
                    <div className="api-metric-note">{t("apiAccess:allStatusesNote")}</div>
                  </article>
                  <article className="api-metric-card">
                    <div className="api-metric-label">{t("apiAccess:publishedVersion")}</div>
                    <div className="api-metric-value">{access.workflow?.published_version ?? "—"}</div>
                    <div className="api-metric-note">{t("apiAccess:current")}</div>
                  </article>
                  <article className="api-metric-card">
                    <div className="api-metric-label">{t("common:status")}</div>
                    <div className="api-metric-value">{access.isPublished ? t("apiAccess:published") : t("apiAccess:unpublished")}</div>
                    <div className="api-metric-note">{access.isPublished ? t("apiAccess:forwardingEnabled") : t("apiAccess:publishToEnable")}</div>
                  </article>
                </section>

                <section className="api-page-grid">
                  <div className="api-page-col">
                    <PublicEndpointCard workflowId={workflowId} />
                    <InvocationExampleCard workflowId={workflowId} definition={access.workflow.definition} />
                    <RunHistoryCard workflowId={workflowId} />
                  </div>
                  <div className="api-page-col">
                    <ApiKeyManagerCard access={access} workflowId={workflowId} />
                    <ReadinessCard isPublished={access.isPublished} keys={access.keys} workflowId={workflowId} />
                  </div>
                </section>
              </>
            ),
          },
          ...(canViewUsage ? [{
            key: "usage",
            label: t("apiAccess:usage"),
            children: <ApiUsageTab workflowId={workflowId} keys={access.keys} />,
          }] : []),
        ]}
      />
    </section>
  );
}
