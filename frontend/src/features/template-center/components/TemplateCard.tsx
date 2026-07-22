import { createElement } from "react";

import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { getTemplateIcon } from "@/components/Icons/IconRegistry";
import TemplateTopologyPreview, {
  type TemplateTopologyVariant
} from "@/features/template-center/components/TemplateTopologyPreview";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";

interface TemplateCardProps {
  template: WorkflowTemplate;
  onApply: (template: WorkflowTemplate) => void;
  onExport: (template: WorkflowTemplate) => void;
  title?: string;
  description?: string;
  topology?: TemplateTopologyVariant;
}

export default function TemplateCard({
  template,
  onApply,
  onExport,
  title,
  description,
  topology
}: TemplateCardProps) {
  const { t } = useTranslation("templates");
  const displayTitle = title ?? template.name;
  const displayDescription = description ?? template.description;
  const categoryLabel = template.category === "comparison" ? t("compare") : t("starter");
  const supportedInputs = template.supported_input_types
    .map((inputType) => inputType.split("/")[1] ?? inputType)
    .slice(0, 3)
    .join(" / ");
  const outputLabel = template.default_output_format.toUpperCase();

  return (
    <article className="template-center-card" data-testid="template-card">
      <div className="template-center-card-topline">
        <span className="template-center-card-category">{categoryLabel}</span>
        <div className="template-center-card-icon" aria-hidden>
          {createElement(getTemplateIcon(template.id), { size: 24 })}
        </div>
      </div>
      <div className="template-center-card-copy">
        <h3>{displayTitle}</h3>
        <p>{displayDescription}</p>
      </div>
      {topology ? (
        <div className="template-center-card-preview">
          <TemplateTopologyPreview variant={topology} />
        </div>
      ) : null}
      <div className="template-center-card-tags">
        {template.tags.slice(0, 3).map((tag) => (
          <span className="template-center-card-tag" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className="template-center-card-metadata">
        <div className="template-center-card-metadata-item">
          <span className="template-center-card-metadata-label">{t("input")}</span>
          <strong>{supportedInputs}</strong>
        </div>
        <div className="template-center-card-metadata-item">
          <span className="template-center-card-metadata-label">{t("output")}</span>
          <strong>{outputLabel}</strong>
        </div>
      </div>
      <div className="template-center-card-cta-note">{t("applyNote")}</div>
      <div className="template-center-card-actions">
        <Button onClick={() => onApply(template)} type="primary">
          {t("applyNow")}
        </Button>
        <Button onClick={() => onExport(template)}>{t("export")}</Button>
      </div>
    </article>
  );
}
