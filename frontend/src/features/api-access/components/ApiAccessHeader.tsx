import { Button } from "antd";
import { useTranslation } from "react-i18next";
import type { WorkflowDetailResponse } from "@/services/workflowApi";

interface Props {
  workflow: WorkflowDetailResponse;
}

export default function ApiAccessHeader({ workflow }: Props) {
  const { t } = useTranslation("apiAccess");
  return (
    <header className="api-forward-toolbar" data-testid="api-access-header">
      <div>
        <span className="kicker">{t("workflowAction")}</span>
        <h1>{t("apiForward")}</h1>
        <p className="description">
          {t("headerDescription")}
        </p>
        <div className="tag-row">
          <span className="tag tag-blue">
            {workflow.name?.trim() ? workflow.name : t("untitledWorkflow")}
          </span>
          {workflow.published_version ? (
            <span className="tag tag-success">
              {t("publishedVersionLabel", { version: workflow.published_version })}
            </span>
          ) : (
            <span className="tag">{t("unpublished")}</span>
          )}
          <span className="tag tag-purple">
            {t("workflowId")}: <code>{workflow.id}</code>
          </span>
          {workflow.published_version && (
            <span className="tag tag-success">{t("forwardingEnabled")}</span>
          )}
          {workflow.latest_version ? (
            <span className="tag">{t("latestVersionLabel", { version: workflow.latest_version })}</span>
          ) : null}
        </div>
      </div>
      <div className="toolbar-actions">
        <Button href={`/workflows/${workflow.id}`}>{t("backEditor")}</Button>
        <Button type="primary" href="#api-keys">
          {t("generateKey")}
        </Button>
      </div>
    </header>
  );
}
