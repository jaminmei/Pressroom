import { createElement } from "react";

import { Button, Card, Modal, Space, Typography } from "antd";

import { getTemplateIcon } from "@/components/Icons/IconRegistry";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";
import { useTranslation } from "react-i18next";

interface TemplateDialogProps {
  open: boolean;
  onCancel: () => void;
  onApply: (template: WorkflowTemplate) => void;
}

export default function TemplateDialog({ open, onCancel, onApply }: TemplateDialogProps) {
  const { t } = useTranslation(["workflows", "templates"]);
  const localizedTemplate = (template: WorkflowTemplate) => {
    const key = template.id === "tpl-ocr-basic" ? "ocr" : template.id === "tpl-vlm-basic" ? "vlm" : "compare";
    return {
      title: t(`templates:meta.${key}.title`, { defaultValue: template.name }),
      description: t(`templates:meta.${key}.description`, { defaultValue: template.description })
    };
  };

  return (
    <Modal destroyOnHidden footer={null} onCancel={onCancel} open={open} title={t("editorText.selectTemplate")}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {BUILTIN_TEMPLATES.map((template) => {
          const copy = localizedTemplate(template);
          return (
          <Card key={template.id} size="small" title={<><span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: 8 }}>{createElement(getTemplateIcon(template.id), { size: 32 })}</span>{copy.title}</>}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Typography.Text type="secondary">{copy.description}</Typography.Text>
              <Button onClick={() => onApply(template)} type="primary">
                {t("editorText.applyTemplate")}
              </Button>
            </Space>
          </Card>
          );
        })}
      </Space>
    </Modal>
  );
}
