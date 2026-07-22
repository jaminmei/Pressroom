import type { TFunction } from "i18next";

import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";

const META_KEY_BY_TEMPLATE_ID: Record<string, "ocr" | "vlm" | "compare"> = {
  "tpl-ocr-basic": "ocr",
  "tpl-vlm-basic": "vlm",
  "tpl-compare-ocr-vlm": "compare"
};

const LABEL_KEY_BY_NODE_TYPE: Record<string, string> = {
  "input/pdf": "pdfInput",
  "processor/document_to_image": "documentToImage",
  "engine/ocr": "ocr",
  "engine/model": "model",
  "end/final": "end"
};

export function localizeWorkflowTemplate(template: WorkflowTemplate, t: TFunction): WorkflowTemplate {
  const metaKey = META_KEY_BY_TEMPLATE_ID[template.id];

  return {
    ...template,
    name: metaKey ? t(`templates:meta.${metaKey}.title`, { defaultValue: template.name }) : template.name,
    description: metaKey
      ? t(`templates:meta.${metaKey}.description`, { defaultValue: template.description })
      : template.description,
    nodes: template.nodes.map((node) => {
      const labelKey = LABEL_KEY_BY_NODE_TYPE[node.type];
      return labelKey
        ? { ...node, data: { ...node.data, label: t(`workflows:editorText.templateNodeLabels.${labelKey}`) } }
        : node;
    })
  };
}
