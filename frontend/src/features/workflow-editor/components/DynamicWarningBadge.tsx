import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import type { DynamicWarning } from "@/features/workflow-editor/store";

interface DynamicWarningBadgeProps {
  warnings: DynamicWarning[];
  nodeId: string;
}

export default function DynamicWarningBadge({ warnings, nodeId }: DynamicWarningBadgeProps) {
  const { t } = useTranslation("workflows");
  const nodeWarnings = warnings.filter((w) => w.node_id === nodeId);

  if (nodeWarnings.length === 0) {
    return null;
  }

  return (
    <div data-testid="dynamic-warning-badge" style={{ marginTop: 8 }}>
      {nodeWarnings.map((warning, index) => {
        if (warning.code === "MODEL_NO_VISION") {
          return (
            <Alert
              key={`${warning.code}-${index}`}
              type="warning"
              showIcon
              message={t("editorText.modelNoVision")}
              description={t("editorText.modelNoVisionDescription")}
              style={{ marginBottom: 4 }}
            />
          );
        }
        if (warning.code === "MODEL_NOT_SELECTED") {
          return (
            <Alert
              key={`${warning.code}-${index}`}
              type="info"
              showIcon
              message={t("editorText.selectVisionModel")}
              style={{ marginBottom: 4 }}
            />
          );
        }
        return (
          <Alert
            key={`${warning.code}-${index}`}
            type={warning.severity === "info" ? "info" : "warning"}
            showIcon
            message={warning.message}
            style={{ marginBottom: 4 }}
          />
        );
      })}
    </div>
  );
}
