import { Card } from "antd";
import { useTranslation } from "react-i18next";

import {
  buildPublicApiHealthPath,
  buildPublicWorkflowRunResultsPath,
  buildPublicWorkflowRunsPath,
  buildPublicWorkflowRunStatusPath,
} from "@/features/api-access/utils/apiAccessExamples";

interface Props {
  workflowId: string;
}

function CurlBlock({ title, children }: { title: string; children: string }) {
  return (
    <div className="api-run-endpoint">
      <h3>{title}</h3>
      <pre>
        <code>{children}</code>
      </pre>
    </div>
  );
}

export default function RunHistoryCard({ workflowId }: Props) {
  const { t } = useTranslation("apiAccess");
  const healthUrl = buildPublicApiHealthPath();
  const statusUrl = buildPublicWorkflowRunStatusPath();
  const resultsUrl = buildPublicWorkflowRunResultsPath();
  const historyUrl = buildPublicWorkflowRunsPath(workflowId);

  return (
    <Card data-testid="run-history-card" className="api-code-card">
      <div className="panel-head">
        <div>
          <h2>{t("runQueryEndpoints")}</h2>
          <p className="mini-muted">
            {t("runQueryDescription")}
          </p>
        </div>
      </div>
      <div className="api-run-endpoint-list">
        <CurlBlock title="Health">{`curl "${healthUrl}"`}</CurlBlock>
        <CurlBlock title="Status">{`curl "${statusUrl}" \\
  -H "Authorization: Bearer dca_..."`}</CurlBlock>
        <CurlBlock title="Results">{`curl "${resultsUrl}" \\
  -H "Authorization: Bearer dca_..."`}</CurlBlock>
        <CurlBlock title="History">{`curl "${historyUrl}" \\
  -H "Authorization: Bearer dca_..."`}</CurlBlock>
      </div>
    </Card>
  );
}
