import { CopyOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card } from "antd";
import { useTranslation } from "react-i18next";

import {
  buildPublicWorkflowRunPath,
  buildPublicWorkflowUploadPath,
} from "@/features/api-access/utils/apiAccessExamples";

interface Props {
  workflowId: string;
}

export default function PublicEndpointCard({ workflowId }: Props) {
  const { t } = useTranslation("apiAccess");
  const { message } = AntApp.useApp();
  const runEndpoint = buildPublicWorkflowRunPath(workflowId);
  const uploadEndpoint = buildPublicWorkflowUploadPath(workflowId);

  const copyEndpoint = (endpoint: string) => {
    void navigator.clipboard.writeText(endpoint).then(() => message.success(t("endpointCopied")));
  };

  return (
    <Card data-testid="public-endpoint-card">
      <div className="panel-head">
        <div>
          <h2>{t("publicEndpoint")}</h2>
          <p className="mini-muted">{t("endpointDescription")}</p>
        </div>
      </div>
      <div className="endpoint-box">
        <div className="endpoint-line">
          <span className="method">POST</span>
          <span className="endpoint-kind">{t("jsonRun")}</span>
          <code className="path">{runEndpoint}</code>
          <Button
            aria-label={t("copyJsonEndpoint")}
            icon={<CopyOutlined />}
            onClick={() => copyEndpoint(runEndpoint)}
            size="small"
            type="text"
          />
        </div>
        <div className="endpoint-line">
          <span className="method">POST</span>
          <span className="endpoint-kind">{t("fileUpload")}</span>
          <code className="path">{uploadEndpoint}</code>
          <Button
            aria-label={t("copyUploadEndpoint")}
            icon={<CopyOutlined />}
            onClick={() => copyEndpoint(uploadEndpoint)}
            size="small"
            type="text"
          />
        </div>
        <p className="mini-muted">{t("endpointHelp")}</p>
      </div>
    </Card>
  );
}
