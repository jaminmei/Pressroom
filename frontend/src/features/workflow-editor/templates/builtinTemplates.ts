import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";

const TPL_OCR_BASIC: WorkflowTemplate = {
  id: "tpl-ocr-basic",
  name: "PDF → OCR",
  description: "PDF 轉圖片後使用 OCR 辨識文字，適合文字為主的標準文檔",
  icon: "tpl-ocr-basic",
  category: "basic",
  tags: ["ocr", "pdf"],
  supported_input_types: ["application/pdf"],
  default_output_format: "markdown",
  nodes: [
    {
      id: "input_1",
      type: "input/pdf",
      position: { x: 100, y: 250 },
      data: {
        label: "PDF 輸入",
        config: { file: "$file_0" }
      }
    },
    {
      id: "processor_1",
      type: "processor/document_to_image",
      position: { x: 350, y: 250 },
      data: {
        label: "文件轉圖片",
        config: { pages: "1" }
      }
    },
    {
      id: "engine_1",
      type: "engine/ocr",
      position: { x: 600, y: 250 },
      data: {
        label: "OCR Engine",
        config: { language: "ch", use_angle_cls: true }
      }
    },
    {
      id: "end_1",
      type: "end/final",
      position: { x: 900, y: 250 },
      data: {
        label: "End",
        config: {}
      }
    }
  ],
  connections: [
    { id: "e-input_1-processor_1", source: "input_1", target: "processor_1" },
    { id: "e-processor_1-engine_1", source: "processor_1", target: "engine_1" },
    { id: "e-engine_1-end_1", source: "engine_1", target: "end_1" }
  ]
};

const TPL_VLM_BASIC: WorkflowTemplate = {
  id: "tpl-vlm-basic",
  name: "PDF → Model",
  description: "PDF 轉圖片後使用 Model 端到端轉換，適合複雜版面（表格、圖文混排）",
  icon: "tpl-vlm-basic",
  category: "basic",
  tags: ["model", "vlm", "pdf"],
  supported_input_types: ["application/pdf"],
  default_output_format: "markdown",
  nodes: [
    {
      id: "input_1",
      type: "input/pdf",
      position: { x: 100, y: 250 },
      data: {
        label: "PDF 輸入",
        config: { file: "$file_0" }
      }
    },
    {
      id: "processor_1",
      type: "processor/document_to_image",
      position: { x: 350, y: 250 },
      data: {
        label: "文件轉圖片",
        config: { pages: "1" }
      }
    },
    {
      id: "engine_1",
      type: "engine/model",
      position: { x: 600, y: 250 },
      data: {
        label: "Model Engine",
        config: {
          prompt: "Analyze this document and extract all content.\n\nOutput JSON with a \"result\" key containing the full extracted text, and a \"structured\" key with block-level detail:\n{\"result\": \"full extracted text\", \"structured\": {\"blocks\": [{\"type\": \"title\"|\"paragraph\"|\"list\"|\"table\"|\"figure\", \"text\": \"...\", \"level\": 1-6 (titles only), \"confidence\": 0.0-1.0}]}}\n\nRules:\n1. type=\"title\" for titles with level (1=main, 2=subtitle)\n2. type=\"paragraph\" for paragraphs\n3. type=\"list\" for lists\n4. type=\"table\" for tables (Markdown format)\n5. type=\"figure\" for images/diagrams (describe content)\n6. Each block needs a confidence value (0-1)\nOutput only JSON."
        }
      }
    },
    {
      id: "end_1",
      type: "end/final",
      position: { x: 950, y: 250 },
      data: {
        label: "End",
        config: {}
      }
    }
  ],
  connections: [
    { id: "e-input_1-processor_1", source: "input_1", target: "processor_1" },
    { id: "e-processor_1-engine_1", source: "processor_1", target: "engine_1" },
    { id: "e-engine_1-end_1", source: "engine_1", target: "end_1" }
  ]
};

const TPL_COMPARE_OCR_VLM: WorkflowTemplate = {
  id: "tpl-compare-ocr-vlm",
  name: "OCR vs Model 對比",
  description: "同一 PDF 同時用 OCR 和 Model 轉換，並排對比輸出效果",
  icon: "tpl-compare-ocr-vlm",
  category: "comparison",
  tags: ["ocr", "model", "compare", "pdf"],
  supported_input_types: ["application/pdf"],
  default_output_format: "markdown",
  nodes: [
    {
      id: "input_1",
      type: "input/pdf",
      position: { x: 100, y: 250 },
      data: {
        label: "PDF 輸入",
        config: { file: "$file_0" }
      }
    },
    {
      id: "processor_1",
      type: "processor/document_to_image",
      position: { x: 350, y: 250 },
      data: {
        label: "文件轉圖片",
        config: { pages: "1" }
      }
    },
    {
      id: "engine_ocr",
      type: "engine/ocr",
      position: { x: 600, y: 150 },
      data: {
        label: "OCR Engine",
        config: { language: "ch", use_angle_cls: true }
      }
    },
    {
      id: "engine_vlm",
      type: "engine/model",
      position: { x: 600, y: 350 },
      data: {
        label: "Model Engine",
        config: {
          prompt: "Analyze this document and extract all content.\n\nOutput JSON with a \"result\" key containing the full extracted text, and a \"structured\" key with block-level detail:\n{\"result\": \"full extracted text\", \"structured\": {\"blocks\": [{\"type\": \"title\"|\"paragraph\"|\"list\"|\"table\"|\"figure\", \"text\": \"...\", \"level\": 1-6 (titles only), \"confidence\": 0.0-1.0}]}}\n\nRules:\n1. type=\"title\" for titles with level (1=main, 2=subtitle)\n2. type=\"paragraph\" for paragraphs\n3. type=\"list\" for lists\n4. type=\"table\" for tables (Markdown format)\n5. type=\"figure\" for images/diagrams (describe content)\n6. Each block needs a confidence value (0-1)\nOutput only JSON."
        }
      }
    },
    {
      id: "end_1",
      type: "end/final",
      position: { x: 950, y: 250 },
      data: {
        label: "End",
        config: {}
      }
    }
  ],
  connections: [
    { id: "e-input_1-processor_1", source: "input_1", target: "processor_1" },
    { id: "e-processor_1-engine_ocr", source: "processor_1", target: "engine_ocr" },
    { id: "e-processor_1-engine_vlm", source: "processor_1", target: "engine_vlm" },
    { id: "e-engine_ocr-end_1", source: "engine_ocr", target: "end_1" },
    { id: "e-engine_vlm-end_1", source: "engine_vlm", target: "end_1" }
  ]
};

export const BUILTIN_TEMPLATES: WorkflowTemplate[] = [
  TPL_OCR_BASIC,
  TPL_VLM_BASIC,
  TPL_COMPARE_OCR_VLM
];
