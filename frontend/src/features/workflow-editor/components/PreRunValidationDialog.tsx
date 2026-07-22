import { Alert, Modal, Space, Typography } from "antd";
import { CheckCircleFilled, CloseCircleFilled } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import type { DynamicWarning } from "@/features/workflow-editor/store";

const { Text } = Typography;

interface ValidationIssue {
  code: string;
  message: string;
  severity: string;
  node_id?: string | null;
}

export interface PreRunValidationResult {
  static: {
    valid: boolean;
    errors: ValidationIssue[];
    warnings: ValidationIssue[];
  };
  dynamic: {
    warnings: DynamicWarning[];
  };
  provider_health?: {
    checked: boolean;
    warnings: DynamicWarning[];
  };
}

interface PreRunValidationDialogProps {
  open: boolean;
  validationResult: PreRunValidationResult | null;
  onProceed: () => void;
  onCancel: () => void;
}

export default function PreRunValidationDialog({
  open,
  validationResult,
  onProceed,
  onCancel
}: PreRunValidationDialogProps) {
  const { t } = useTranslation(["workflows", "common"]);
  if (!validationResult) {
    return null;
  }

  const { static: staticResult, dynamic: dynamicResult, provider_health: providerHealth } = validationResult;
  const hasStaticErrors = !staticResult.valid;
  const dynamicWarnings = dynamicResult.warnings.filter((w) => w.severity === "warning");
  const dynamicInfos = dynamicResult.warnings.filter((w) => w.severity === "info");
  const healthWarnings = providerHealth?.warnings ?? [];
  const hasBlockingWarnings = dynamicWarnings.length > 0 || healthWarnings.length > 0;
  const hasInfoOnly = !hasBlockingWarnings && dynamicInfos.length > 0;

  // ERROR state: static validation failed
  if (hasStaticErrors) {
    return (
      <Modal
        open={open}
        title={t("editorText.validationErrors")}
        onCancel={onCancel}
        onOk={onCancel}
        cancelButtonProps={{ style: { display: "none" } }}
        okText={t("common:close")}
        data-testid="pre-run-validation-dialog"
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Text>{t("editorText.fixErrors")}</Text>
          {staticResult.errors.map((error, i) => (
            <Alert key={i} type="error" showIcon message={error.message} />
          ))}
        </Space>
      </Modal>
    );
  }

  // WARNING state: dynamic warnings or provider health issues
  if (hasBlockingWarnings) {
    return (
      <Modal
        open={open}
        title={t("editorText.validationWarnings")}
        onCancel={onCancel}
        okText={t("editorText.runAnyway")}
        onOk={onProceed}
        cancelText={t("common:cancel")}
        data-testid="pre-run-validation-dialog"
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          {dynamicWarnings.length > 0 && (
            <>
              <Text strong>{t("editorText.configurationWarnings")}</Text>
              {dynamicWarnings.map((warning, i) => (
                <Alert key={i} type="warning" showIcon message={warning.message} />
              ))}
            </>
          )}
          {providerHealth && (
            <>
              <Text strong style={{ marginTop: dynamicWarnings.length > 0 ? 8 : 0 }}>{t("editorText.providerHealth")}</Text>
              {healthWarnings.length === 0 ? (
                <Alert
                  type="success"
                  showIcon
                  icon={<CheckCircleFilled />}
                  message={t("editorText.allEnginesHealthy")}
                />
              ) : (
                healthWarnings.map((w, i) => (
                  <Alert key={i} type="warning" showIcon icon={<CloseCircleFilled />} message={w.message} />
                ))
              )}
            </>
          )}
          <Text type="secondary">{t("editorText.warningProceed")}</Text>
        </Space>
      </Modal>
    );
  }

  // INFO state: info-only
  if (hasInfoOnly) {
    return (
      <Modal
        open={open}
        title={t("editorText.advisoryNotices")}
        onCancel={onCancel}
        okText={t("editorText.continue")}
        onOk={onProceed}
        cancelText={t("common:cancel")}
        data-testid="pre-run-validation-dialog"
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Text>{t("editorText.advisoryDescription")}</Text>
          {dynamicInfos.map((info, i) => (
            <Alert key={i} type="info" showIcon message={info.message} />
          ))}
        </Space>
      </Modal>
    );
  }

  // Clean state - should not render (parent should not open dialog)
  return null;
}
