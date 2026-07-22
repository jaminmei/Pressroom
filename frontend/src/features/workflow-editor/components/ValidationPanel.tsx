import { CheckCircleOutlined, CloseOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import type { WorkflowValidationIssue } from "@/features/workflow-editor/utils/workflowValidator";

interface ValidationPanelProps {
  blockingErrors: WorkflowValidationIssue[];
  warnings: WorkflowValidationIssue[];
  isOpen: boolean;
  onClose: () => void;
  onSelectIssue: (issue: WorkflowValidationIssue) => void;
}

function IssueList({
  issues,
  onSelectIssue
}: {
  issues: WorkflowValidationIssue[];
  onSelectIssue: (issue: WorkflowValidationIssue) => void;
}) {
  return (
    <ul className="validation-panel-list">
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${issue.nodeId ?? "global"}-${index}`}>
          <button
            className="validation-panel-item"
            onClick={() => onSelectIssue(issue)}
            type="button"
          >
            {issue.message}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function ValidationPanel({
  blockingErrors,
  warnings,
  isOpen,
  onClose,
  onSelectIssue
}: ValidationPanelProps) {
  const { t } = useTranslation("workflows");
  if (!isOpen) {
    return null;
  }

  return (
    <section className="validation-panel" data-testid="validation-panel">
      <div className="validation-panel-header">
        <span className="validation-panel-title">
          {t("editorText.validation")}
          {blockingErrors.length > 0 && (
            <span className="validation-panel-count validation-panel-count-error">{blockingErrors.length}</span>
          )}
          {warnings.length > 0 && (
            <span className="validation-panel-count validation-panel-count-warn">{warnings.length}</span>
          )}
        </span>
        <button aria-label={t("editorText.closePanel")} className="validation-panel-close" onClick={onClose} type="button">
          <CloseOutlined />
        </button>
      </div>
      {blockingErrors.length === 0 && warnings.length === 0 && (
        <div className="validation-panel-success" data-testid="validation-panel-success">
          <CheckCircleOutlined style={{ color: "#52c41a", fontSize: 28 }} />
          <span>{t("editorText.validationPassed")}</span>
        </div>
      )}
      {blockingErrors.length > 0 && (
        <div className="validation-panel-group">
          <h4 className="validation-panel-group-title validation-panel-group-error">
            {t("editorText.blocking")}
          </h4>
          <IssueList issues={blockingErrors} onSelectIssue={onSelectIssue} />
        </div>
      )}
      {warnings.length > 0 && (
        <div className="validation-panel-group">
          <h4 className="validation-panel-group-title validation-panel-group-warn">
            {t("editorText.warnings")}
          </h4>
          <IssueList issues={warnings} onSelectIssue={onSelectIssue} />
        </div>
      )}
    </section>
  );
}
