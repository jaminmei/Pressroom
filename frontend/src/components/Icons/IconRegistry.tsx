import { type DocConvIconComponent, createDocConvIcon } from "./DocConvIcon";
import { DOC_CONV_ICON_PATHS } from "./docconv-icon-paths";

// ─── Category Icons (node types on canvas) ───────────────────────────────────

export const CATEGORY_ICONS = {
  input: createDocConvIcon("InputIcon", DOC_CONV_ICON_PATHS.input),
  processor: createDocConvIcon("ProcessorIcon", DOC_CONV_ICON_PATHS.processor),
  engine: createDocConvIcon("EngineIcon", DOC_CONV_ICON_PATHS.engine),
  output: createDocConvIcon("OutputIcon", DOC_CONV_ICON_PATHS.output),
  end: createDocConvIcon("OutputIcon", DOC_CONV_ICON_PATHS.output),
  default: createDocConvIcon("DefaultIcon", DOC_CONV_ICON_PATHS.default),
} as const;

// ─── Status Icons (task execution states) ────────────────────────────────────

export const STATUS_ICONS = {
  idle: createDocConvIcon("IdleIcon", DOC_CONV_ICON_PATHS.idle),
  pending: createDocConvIcon("PendingIcon", DOC_CONV_ICON_PATHS.pending),
  running: createDocConvIcon("RunningIcon", DOC_CONV_ICON_PATHS.running),
  completed: createDocConvIcon("CompletedIcon", DOC_CONV_ICON_PATHS.completed),
  failed: createDocConvIcon("FailedIcon", DOC_CONV_ICON_PATHS.failed),
  awaiting_input: createDocConvIcon("AwaitingInputIcon", DOC_CONV_ICON_PATHS.awaiting_input),
  awaiting_user_input: createDocConvIcon("AwaitingInputIcon", DOC_CONV_ICON_PATHS.awaiting_input),
  skipped: createDocConvIcon("SkippedIcon", DOC_CONV_ICON_PATHS.skipped),
  cancelled: createDocConvIcon("CancelledIcon", DOC_CONV_ICON_PATHS.cancelled),
} as const;

// ─── Engine Icons (backend engine type identifiers) ──────────────────────────

export const ENGINE_ICONS: Record<string, DocConvIconComponent> = {
  vlm: createDocConvIcon("VlmIcon", DOC_CONV_ICON_PATHS.vlm),
  ocr: createDocConvIcon("OcrIcon", DOC_CONV_ICON_PATHS.ocr),
  text: createDocConvIcon("TextEngineIcon", DOC_CONV_ICON_PATHS.text),
  markitdown: createDocConvIcon("MarkitdownIcon", DOC_CONV_ICON_PATHS.markitdown),
  docling: createDocConvIcon("DoclingIcon", DOC_CONV_ICON_PATHS.docling),
  layout_detection: createDocConvIcon("LayoutDetectionIcon", DOC_CONV_ICON_PATHS.layout_detection),
  image_enhancement: createDocConvIcon("ImageEnhancementIcon", DOC_CONV_ICON_PATHS.image_enhancement),
  image_rotation: createDocConvIcon("ImageRotationIcon", DOC_CONV_ICON_PATHS.image_rotation),
};

// ─── Action Icons (node card buttons) ────────────────────────────────────────

export const ACTION_ICONS = {
  run: createDocConvIcon("RunIcon", DOC_CONV_ICON_PATHS.run),
  rerun: createDocConvIcon("RerunIcon", DOC_CONV_ICON_PATHS.rerun),
  copy: createDocConvIcon("CopyIcon", DOC_CONV_ICON_PATHS.copy),
  delete: createDocConvIcon("DeleteIcon", DOC_CONV_ICON_PATHS.delete),
} as const;

// ─── Template Icons (workflow template cards) ────────────────────────────────

export const TEMPLATE_ICONS: Record<string, DocConvIconComponent> = {
  "tpl-ocr-basic": createDocConvIcon("TplOcrIcon", DOC_CONV_ICON_PATHS["tpl-ocr-basic"]),
  "tpl-vlm-basic": createDocConvIcon("TplVlmIcon", DOC_CONV_ICON_PATHS["tpl-vlm-basic"]),
  "tpl-compare-ocr-vlm": createDocConvIcon("TplCompareIcon", DOC_CONV_ICON_PATHS["tpl-compare-ocr-vlm"]),
  star: createDocConvIcon("DefaultIcon", DOC_CONV_ICON_PATHS.default),
};

// ─── Helper Functions ────────────────────────────────────────────────────────

export function getCategoryIcon(category: string): DocConvIconComponent {
  return (
    CATEGORY_ICONS[category as keyof typeof CATEGORY_ICONS] ??
    CATEGORY_ICONS.default
  );
}

export function getStatusIcon(status: string): DocConvIconComponent {
  return (
    STATUS_ICONS[status as keyof typeof STATUS_ICONS] ?? STATUS_ICONS.idle
  );
}

export function getEngineIcon(engineId: string): DocConvIconComponent {
  return ENGINE_ICONS[engineId] ?? CATEGORY_ICONS.engine;
}

export function getTemplateIcon(templateId: string): DocConvIconComponent {
  return TEMPLATE_ICONS[templateId] ?? TEMPLATE_ICONS.star;
}

export const ProjectsIcon = createDocConvIcon("ProjectsIcon", DOC_CONV_ICON_PATHS.projects);
export const LatestVersionIcon = createDocConvIcon("LatestVersionIcon", DOC_CONV_ICON_PATHS.latest_version);
