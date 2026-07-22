import { createElement } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Col, Row, Typography } from "antd";

import { getTemplateIcon } from "@/components/Icons/IconRegistry";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import { localizeWorkflowTemplate } from "@/features/workflow-editor/templates/localizeTemplate";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";

interface EmptyCanvasGuideProps {
  onApplyTemplate: (template: WorkflowTemplate) => void;
  entryToolbar?: ReactNode;
}

export default function EmptyCanvasGuide({ onApplyTemplate, entryToolbar }: EmptyCanvasGuideProps) {
  const { t } = useTranslation("workflows");
  return (
    <div className="empty-canvas-guide" data-testid="empty-canvas-guide">
      <div className="empty-canvas-guide-header">
        <div className="empty-canvas-guide-copy">
          <span className="empty-canvas-guide-kicker">{t("editorText.quickStart")}</span>
          <Typography.Title level={4} style={{ marginTop: 0 }}>
            {t("editorText.quickStartTitle")}
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            {t("editorText.quickStartIntro")}
          </Typography.Paragraph>
        </div>

        {entryToolbar ? <div className="empty-canvas-guide-entry">{entryToolbar}</div> : null}
      </div>

      <Row gutter={[16, 16]}>
        {BUILTIN_TEMPLATES.map((template) => {
          const localizedTemplate = localizeWorkflowTemplate(template, t);
          return (
            <Col key={template.id} xs={24} xl={8}>
              <Card className="template-card" size="small" title={<><span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: 8 }}>{createElement(getTemplateIcon(template.id), { size: 32 })}</span>{localizedTemplate.name}</>}>
                <Typography.Paragraph type="secondary">{localizedTemplate.description}</Typography.Paragraph>
                <Button onClick={() => onApplyTemplate(template)} size="small" type="primary">
                  {t("editorText.applyOneClick")}
                </Button>
              </Card>
            </Col>
          );
        })}
      </Row>

      <Typography.Text type="secondary">{t("editorText.quickStartDescription")}</Typography.Text>
    </div>
  );
}
