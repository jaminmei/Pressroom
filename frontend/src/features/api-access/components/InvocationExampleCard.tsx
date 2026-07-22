import { CopyOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Tabs } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  buildCurlExample,
  buildUploadCurlExample,
} from "@/features/api-access/utils/apiAccessExamples";
import type { WorkflowImportExportPayload } from "@/services/workflowApi";

interface Props {
  workflowId: string;
  definition?: WorkflowImportExportPayload | null;
}

type ExampleTab = "url" | "upload";

export default function InvocationExampleCard({ workflowId, definition }: Props) {
  const { t } = useTranslation("apiAccess");
  const { message } = AntApp.useApp();
  const [tab, setTab] = useState<ExampleTab>("url");

  const urlExample = buildCurlExample(workflowId, definition);
  const uploadExample = buildUploadCurlExample(workflowId);
  const example = tab === "url" ? urlExample : uploadExample;

  const copy = () => {
    void navigator.clipboard.writeText(example).then(() => message.success(t("exampleCopied")));
  };

  return (
    <Card data-testid="invocation-example-card" className="api-code-card">
      <div className="panel-head">
        <div>
          <h2>{t("invocationExample")}</h2>
          <p className="mini-muted">{t("exampleDescription")}</p>
        </div>
        <Button icon={<CopyOutlined />} onClick={copy} size="small">{t("copyCurl")}</Button>
      </div>
      <Tabs
        activeKey={tab}
        data-testid="invocation-example-tabs"
        items={[
          { key: "url", label: t("urlMode"), children: null },
          { key: "upload", label: t("uploadMode"), children: null },
        ]}
        onChange={(key) => setTab(key as ExampleTab)}
      />
      <pre style={{
        margin: 0, padding: 12, background: "#151420", color: "#f3f0ff",
        borderRadius: 12, fontSize: 12, lineHeight: 1.65, overflow: "auto",
      }}>
        <code>{example}</code>
      </pre>
    </Card>
  );
}
