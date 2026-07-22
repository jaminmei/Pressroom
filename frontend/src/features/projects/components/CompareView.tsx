import {
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import { Typography } from "antd";
import { useTranslation } from "react-i18next";

import type { FieldDiff } from "@/features/projects/types";
import { PermissionButton } from "@/components/Permissions/PermissionButton";

const { Text } = Typography;

export interface CompareViewProps {
  documentId: string;
  expectedContent: string;
  actualContent: string;
  differences: FieldDiff[];
  onAcceptAsGT?: () => void;
  onReject?: () => void;
}

export default function CompareView({
  documentId,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  expectedContent: _expectedContent,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  actualContent: _actualContent,
  differences,
  onAcceptAsGT,
  onReject,
}: CompareViewProps) {
  const { t } = useTranslation("projects");
  const hasActions = onAcceptAsGT || onReject;

  if (differences.length === 0) {
    return (
      <div className="cv-compare-empty" data-testid="cv-compare-empty">
        <CheckCircleOutlined style={{ color: "var(--success)", fontSize: 24 }} />
        <Text type="secondary">{t("allFieldsMatch")}</Text>
      </div>
    );
  }

  return (
    <div className="cv-compare-wrapper" data-testid="cv-compare-view">
      <div className="cv-compare-view">
        <div className="cv-compare-columns">
          <div className="cv-compare-col cv-compare-col-expected">
            <div className="cv-compare-col-header">{t("originalGroundTruth")}</div>
            {differences.map((field) => (
              <div
                key={field.fieldName}
                className={`cv-compare-field ${field.status === "mismatch" ? "cv-compare-field-diff" : ""}`}
              >
                <span className="cv-compare-field-name">{field.fieldName}</span>
                <span className="cv-compare-field-value">{field.expected}</span>
              </div>
            ))}
          </div>

          <div className="cv-compare-col cv-compare-col-actual">
            <div className="cv-compare-col-header">{t("ocrOutput")}</div>
            {differences.map((field) => (
              <div
                key={field.fieldName}
                className={`cv-compare-field ${field.status === "mismatch" ? "cv-compare-field-diff" : ""}`}
              >
                <span className="cv-compare-field-name">{field.fieldName}</span>
                <span className="cv-compare-field-value">
                  {field.actual}
                  {field.status === "mismatch" && (
                    <span className="cv-differs-marker">← {t("differs")}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {hasActions && (
        <div className="cv-compare-actions" data-testid={`cv-compare-actions-${documentId}`}>
          {onAcceptAsGT && (
            <PermissionButton
              capability="ground_truth.accept_reject"
              type="primary"
              icon={<CheckOutlined />}
              onClick={onAcceptAsGT}
              data-testid={`cv-accept-gt-${documentId}`}
            >
              {t("acceptAsGroundTruth")}
            </PermissionButton>
          )}
          {onReject && (
            <PermissionButton
              capability="ground_truth.accept_reject"
              danger
              icon={<CloseOutlined />}
              onClick={onReject}
              data-testid={`cv-reject-${documentId}`}
            >
              {t("reject")}
            </PermissionButton>
          )}
        </div>
      )}
    </div>
  );
}
