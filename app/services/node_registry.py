from __future__ import annotations

from app.models.node_registry import InputPortDef, NodeCategory, NodeDefinition, NodeRegistry


class NodeRegistryService:
    """Static node registry used by workflow validation and FE node palette."""

    def __init__(self) -> None:
        self._registry = NodeRegistry(
            categories=[
                NodeCategory(
                    category_id="input",
                    display_name="輸入源",
                    description="文件輸入節點",
                ),
                NodeCategory(
                    category_id="processor",
                    display_name="預處理器",
                    description="文件預處理節點",
                ),
                NodeCategory(
                    category_id="engine",
                    display_name="轉換引擎",
                    description="核心轉換引擎",
                ),
                NodeCategory(
                    category_id="end",
                    display_name="終點",
                    description="Workflow 正式終點與結果入口",
                ),
            ],
            nodes=[
                NodeDefinition(
                    node_type="input/pdf",
                    display_name="PDF 輸入",
                    category="input",
                    description="上傳 PDF 文件作為輸入",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "file",
                                "accept": ["application/pdf"],
                                "max_size_mb": 50,
                            },
                        },
                        "required": ["file"],
                    },
                    input_ports=[],
                    output_types=["application/pdf"],
                    max_inputs=0,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="input/image",
                    display_name="圖片輸入",
                    category="input",
                    description="上傳圖片作為輸入",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "file",
                                "accept": [
                                    "image/png",
                                    "image/jpeg",
                                    "image/jpg",
                                    "image/webp",
                                    "image/bmp",
                                    "image/tiff",
                                    "image/tif",
                                ],
                                "max_size_mb": 20,
                            }
                        },
                        "required": ["file"],
                    },
                    input_ports=[],
                    output_types=["image/*"],
                    max_inputs=0,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="input/text",
                    display_name="Text 輸入",
                    category="input",
                    description="上傳純文字文件作為輸入",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "file",
                                "accept": ["text/plain"],
                                "max_size_mb": 10,
                            }
                        },
                        "required": ["file"],
                    },
                    input_ports=[],
                    output_types=["text/plain"],
                    max_inputs=0,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="processor/layout_detection",
                    display_name="Layout Detection",
                    category="processor",
                    description="檢測文件版面結構 (PPstructure)",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "selected_types": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "Text",
                                        "Title",
                                        "Table",
                                        "Figure",
                                        "List",
                                        "Figure_caption",
                                        "Table_caption",
                                        "Header",
                                        "Footer",
                                        "Reference",
                                        "Equation",
                                    ],
                                    "enum_metadata": {
                                        "Text": {"display_name": "Text (文本)"},
                                        "Title": {"display_name": "Title (标题)"},
                                        "Table": {"display_name": "Table (表格)"},
                                        "Figure": {"display_name": "Figure (图片)"},
                                        "List": {"display_name": "List (列表)"},
                                        "Figure_caption": {
                                            "display_name": "Figure Caption (图片说明)"
                                        },
                                        "Table_caption": {
                                            "display_name": "Table Caption (表格说明)"
                                        },
                                        "Header": {"display_name": "Header (页眉)"},
                                        "Footer": {"display_name": "Footer (页脚)"},
                                        "Reference": {"display_name": "Reference (参考文献)"},
                                        "Equation": {"display_name": "Equation (公式)"},
                                    },
                                },
                                "title": "Selected Layout Types",
                                "description": "Select which layout types to output.",
                                "default": [],
                            },
                        },
                    },
                    input_types=["image/*"],
                    input_ports=[
                        InputPortDef(
                            name="image",
                            accepted_types=["image/*"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["application/x-layout-result"],
                    max_inputs=1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="processor/image_enhance",
                    display_name="圖像增強",
                    category="processor",
                    description="圖像預處理增強（對比度、銳化、去噪）",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "clahe_enabled": {
                                "type": "boolean",
                                "default": True,
                            },
                            "clahe_clip_limit": {
                                "type": "number",
                                "default": 2.0,
                                "minimum": 0.1,
                                "maximum": 5.0,
                            },
                            "denoise": {
                                "type": "boolean",
                                "default": False,
                            },
                            "sharpen": {
                                "type": "boolean",
                                "default": False,
                            },
                        },
                    },
                    input_types=["image/*"],
                    input_ports=[
                        InputPortDef(
                            name="image",
                            accepted_types=["image/*"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["image/*"],
                    max_inputs=1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="processor/rotate",
                    display_name="圖像旋轉",
                    category="processor",
                    description="圖像旋轉（含自動方向檢測）",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "angle": {
                                "type": "number",
                                "title": "Rotation Angle",
                                "description": (
                                    "Rotation angle in degrees (clockwise). "
                                    "Positive values rotate clockwise, "
                                    "negative rotates counter-clockwise."
                                ),
                                "default": 0,
                                "minimum": -360,
                                "maximum": 360,
                            },
                            "auto_rotate": {
                                "type": "boolean",
                                "title": "Auto Rotate",
                                "description": "Automatically detect and correct image orientation",
                                "default": False,
                            },
                        },
                    },
                    input_types=["image/*"],
                    input_ports=[
                        InputPortDef(
                            name="image",
                            accepted_types=["image/*"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["image/*"],
                    max_inputs=1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="processor/document_to_image",
                    display_name="文件轉圖片",
                    category="processor",
                    description="將文件（PDF 等）轉換為 PNG 圖片",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "pages": {
                                "type": "string",
                                "default": "1",
                                "description": (
                                    "要轉換的頁碼，例如 '1'、'1-3'、'all'。"
                                    "預設為第 1 頁（僅對多頁文件有效）"
                                ),
                            },
                        },
                        "required": [],
                    },
                    input_types=["application/pdf"],
                    input_ports=[
                        InputPortDef(
                            name="document",
                            accepted_types=["application/pdf"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["image/*"],
                    max_inputs=1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="engine/ocr",
                    display_name="OCR",
                    category="engine",
                    description="OCR 文字辨識引擎",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "language": {
                                "type": "string",
                                "enum": ["ch"],
                                "default": "ch",
                                "title": "Language",
                                "description": "OCR recognition language",
                            },
                            "use_angle_cls": {
                                "type": "boolean",
                                "default": True,
                                "title": "Use Angle Classifier",
                                "description": "Detect and correct text orientation",
                            },
                            "det_thresh": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": 0.9,
                                "default": 0.3,
                                "title": "Detection Threshold",
                                "description": "Text detection threshold (lower = more sensitive)",
                            },
                            "det_box_thresh": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": 0.9,
                                "default": 0.6,
                                "title": "Box Threshold",
                                "description": "Box confidence threshold for filtering",
                            },
                        },
                        "required": [],
                    },
                    input_types=[
                        "image/*",
                        "image/cropped_blocks",
                        "application/x-layout-result",
                    ],
                    input_ports=[
                        InputPortDef(
                            name="images",
                            accepted_types=[
                                "image/*",
                                "image/cropped_blocks",
                                "application/x-layout-result",
                            ],
                            required=True,
                            max_connections=-1,
                        ),
                    ],
                    output_types=["text/raw"],
                    max_inputs=-1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="engine/model",
                    display_name="Model",
                    category="engine",
                    description="統一模型引擎（VLM + LLM）",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "output_type": {
                                "type": "string",
                                "enum": ["text", "json_schema"],
                                "enum_metadata": {
                                    "text": {"display_name": "Text (Free-form)"},
                                    "json_schema": {"display_name": "JSON Schema (Structured)"},
                                },
                                "default": "text",
                                "title": "Output Type",
                                "description": (
                                    "Choose output format: plain text or structured JSON"
                                ),
                            },
                            "model": {
                                "type": "string",
                                "title": "Model",
                                "description": "VLM model to use for document understanding",
                                "enum": [
                                    "gpt-4o-240806",
                                    "gpt-4.1",
                                    "gpt-4.1-mini",
                                    "gpt-4.1-nano",
                                    "gpt-5",
                                    "gpt-5.1",
                                    "gpt-5.2",
                                    "gpt-5-mini",
                                    "gpt-5-nano",
                                ],
                                "enum_metadata": {
                                    "gpt-4o-240806": {
                                        "group": "gpt_regular",
                                        "display_name": "GPT-4o",
                                        "has_vision": True,
                                    },
                                    "gpt-4.1": {
                                        "group": "gpt_regular",
                                        "display_name": "GPT-4.1",
                                        "has_vision": True,
                                    },
                                    "gpt-4.1-mini": {
                                        "group": "gpt_regular",
                                        "display_name": "GPT-4.1 Mini",
                                        "has_vision": True,
                                    },
                                    "gpt-4.1-nano": {
                                        "group": "gpt_regular",
                                        "display_name": "GPT-4.1 Nano",
                                        "has_vision": True,
                                    },
                                    "gpt-5": {
                                        "group": "gpt_inference",
                                        "display_name": "GPT-5",
                                        "has_vision": True,
                                    },
                                    "gpt-5.1": {
                                        "group": "gpt_inference",
                                        "display_name": "GPT-5.1",
                                        "has_vision": True,
                                    },
                                    "gpt-5.2": {
                                        "group": "gpt_inference",
                                        "display_name": "GPT-5.2",
                                        "has_vision": True,
                                    },
                                    "gpt-5-mini": {
                                        "group": "gpt_inference",
                                        "display_name": "GPT-5 Mini",
                                        "has_vision": True,
                                    },
                                    "gpt-5-nano": {
                                        "group": "gpt_inference",
                                        "display_name": "GPT-5 Nano",
                                        "has_vision": True,
                                    },
                                },
                                "default": "gpt-4.1",
                            },
                            "prompt": {
                                "type": "string",
                                "title": "Custom Prompt",
                                "description": (
                                    "Instruction for the VLM model. "
                                    "Default extracts structured content."
                                ),
                                "default": (
                                    "Analyze this document and extract all content.\n\n"
                                    'Output JSON with a "result" key containing '
                                    "the full extracted text, "
                                    'and a "structured" key with block-level '
                                    "detail:\n"
                                    '{"result": "full extracted text", '
                                    '"structured": {"blocks": '
                                    '[{"type": "title"|"paragraph"|'
                                    '"list"|"table"|"figure", '
                                    '"text": "...", "level": 1-6 '
                                    '(titles only), "confidence": '
                                    "0.0-1.0}]}}\n\n"
                                    "Rules:\n"
                                    '1. type="title" for titles with level (1=main, 2=subtitle)\n'
                                    '2. type="paragraph" for paragraphs\n'
                                    '3. type="list" for lists\n'
                                    '4. type="table" for tables (Markdown format)\n'
                                    '5. type="figure" for images/diagrams (describe content)\n'
                                    "6. Each block needs a confidence value (0-1)\n"
                                    "Output only JSON."
                                ),
                            },
                            "temperature": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 2,
                                "default": 0,
                                "title": "Temperature",
                                "description": (
                                    "Sampling temperature (not available for GPT-5.x inference "
                                    "models)"
                                ),
                                "applicable_groups": ["gpt_regular"],
                            },
                            "max_tokens": {
                                "type": "integer",
                                "minimum": 100,
                                "maximum": 16000,
                                "default": 4096,
                                "title": "Max Tokens",
                                "description": "Maximum tokens to generate (for GPT-4.x models)",
                                "applicable_groups": ["gpt_regular"],
                            },
                            "max_completion_tokens": {
                                "type": "integer",
                                "minimum": 100,
                                "maximum": 32000,
                                "default": 4096,
                                "title": "Max Completion Tokens",
                                "description": (
                                    "Maximum completion tokens (for GPT-5.x inference models)"
                                ),
                                "applicable_groups": ["gpt_inference"],
                            },
                            "reasoning_effort": {
                                "type": "string",
                                "enum": ["MINIMAL", "LOW", "MEDIUM", "HIGH"],
                                "default": "MINIMAL",
                                "title": "Reasoning Effort",
                                "description": "Reasoning intensity for GPT-5.x models",
                                "applicable_groups": ["gpt_inference"],
                            },
                            "output_schema": {
                                "type": "string",
                                "schema_type": "json",
                                "title": "Output Schema",
                                "description": (
                                    "JSON Schema for structured output with "
                                    "searchTerm and alias for each field. "
                                    "Leave empty for free-form text generation."
                                ),
                                "default": "",
                            },
                        },
                        "model_groups": {
                            "gpt_regular": {
                                "display_name": "GPT Regular (4.x)",
                                "description": "Standard GPT models with configurable temperature",
                            },
                            "gpt_inference": {
                                "display_name": "GPT Inference (5.x)",
                                "description": "Reasoning models with fixed temperature=1",
                            },
                        },
                        "required": [],
                    },
                    input_types=[
                        "image/*",
                        "image/cropped_blocks",
                        "text/raw",
                        "text/plain",
                        "application/x-layout-result",
                    ],
                    input_ports=[
                        InputPortDef(
                            name="image",
                            accepted_types=[
                                "image/*",
                                "image/cropped_blocks",
                                "application/x-layout-result",
                            ],
                            required=False,
                            max_connections=1,
                        ),
                        InputPortDef(
                            name="text",
                            accepted_types=["text/raw", "text/plain"],
                            required=False,
                            max_connections=1,
                        ),
                    ],
                    output_types=["text/raw"],
                    max_inputs=-1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="engine/text",
                    display_name="Text Engine",
                    category="engine",
                    description="Text 處理引擎",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "encoding": {
                                "type": "string",
                                "enum": [
                                    "auto",
                                    "utf-8",
                                    "utf-8-sig",
                                    "big5",
                                    "gb2312",
                                    "gbk",
                                    "shift_jis",
                                ],
                                "default": "auto",
                                "title": "Character Encoding",
                                "description": (
                                    "Text encoding for parsing. 'auto' will attempt detection."
                                ),
                            },
                            "format_hint": {
                                "type": "string",
                                "enum": ["auto", "plain", "html", "xml", "csv", "json"],
                                "default": "auto",
                                "title": "Format Hint",
                                "description": "Input format hint for better parsing",
                            },
                        },
                        "required": [],
                    },
                    input_types=["text/plain", "text/html"],
                    input_ports=[
                        InputPortDef(
                            name="text",
                            accepted_types=["text/plain", "text/html"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["text/raw"],
                    max_inputs=1,
                    max_outputs=-1,
                ),
                NodeDefinition(
                    node_type="engine/markitdown",
                    display_name="MarkItDown",
                    category="engine",
                    description="MarkItDown 引擎",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "file_extension_hint": {
                                "type": "string",
                                "default": "",
                                "title": "File Extension Hint",
                                "description": (
                                    "Optional file extension hint when not detectable from input"
                                ),
                            }
                        },
                        "required": [],
                    },
                    input_types=["application/pdf", "text/plain", "text/html"],
                    input_ports=[
                        InputPortDef(
                            name="document",
                            accepted_types=["application/pdf", "text/plain", "text/html"],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["text/raw"],
                    max_inputs=1,
                    max_outputs=1,
                ),
                NodeDefinition(
                    node_type="engine/docling",
                    display_name="Docling",
                    category="engine",
                    description="Docling 文檔轉換引擎",
                    config_schema={
                        "type": "object",
                        "properties": {
                            "file_extension_hint": {
                                "type": "string",
                                "default": "",
                                "title": "File Extension Hint",
                                "description": (
                                    "Optional file extension hint when not detectable from input"
                                ),
                            }
                        },
                        "required": [],
                    },
                    input_types=["application/pdf", "text/plain", "text/html", "image/*"],
                    input_ports=[
                        InputPortDef(
                            name="document",
                            accepted_types=[
                                "application/pdf",
                                "text/plain",
                                "text/html",
                                "image/*",
                            ],
                            required=True,
                            max_connections=1,
                        ),
                    ],
                    output_types=["text/raw"],
                    max_inputs=1,
                    max_outputs=1,
                ),
                NodeDefinition(
                    node_type="end/final",
                    display_name="End",
                    category="end",
                    description="Workflow 結果入口與正式終點",
                    config_schema={"type": "object", "properties": {}},
                    input_types=["text/raw", "text/plain", "text/markdown", "image/*"],
                    input_ports=[
                        InputPortDef(
                            name="input",
                            accepted_types=["text/raw", "text/plain", "text/markdown", "image/*"],
                            required=True,
                            max_connections=-1,
                        ),
                    ],
                    output_types=[],
                    max_inputs=-1,
                    max_outputs=0,
                ),
            ],
            connection_rules=[],
        )
        self._by_type = {node.node_type: node for node in self._registry.nodes}

    def get_registry(self) -> NodeRegistry:
        return self._registry

    def get_node_definition(self, node_type: str) -> NodeDefinition | None:
        return self._by_type.get(node_type)

    def get_model_capability(self, node_type: str, model_key: str) -> dict[str, object] | None:
        """Return enum_metadata for a specific model within a node's config_schema.

        Returns None if the node_type or model_key is not found.
        """
        node_def = self.get_node_definition(node_type)
        if node_def is None:
            return None
        properties = node_def.config_schema.get("properties")
        if not isinstance(properties, dict):
            return None
        model_prop = properties.get("model")
        if not isinstance(model_prop, dict):
            return None
        enum_metadata = model_prop.get("enum_metadata")
        if not isinstance(enum_metadata, dict):
            return None
        capability = enum_metadata.get(model_key)
        return dict(capability) if isinstance(capability, dict) else None
