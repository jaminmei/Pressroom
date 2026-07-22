"""ENGINE Type Registry — developer-managed engine type metadata.

ENGINE types define the categories of processing engines available in the
system (OCR, VLM, Text, etc.). Each ENGINE type owns a provider registry
where users can register service instances with parameter schemas.

ENGINE types are hardcoded in this module. Adding a new ENGINE type requires
a code change here + a corresponding node in the frontend node_registry.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineTypeMeta:
    """Metadata for a single ENGINE type."""

    category: str  # matches model_providers.engine_category
    display_name: str  # UI display name
    icon: str  # Lucide-compatible identifier (e.g. "vlm", "ocr")
    description: str  # short description
    default_provider_type: str  # 'openai_compatible' | 'engine_service'
    supported_input_types: list[str]  # MIME types for port matching
    response_formats: list[str]  # supported response_format values
    allow_multiple_models: bool  # True for openai_compatible


ENGINE_TYPES: dict[str, EngineTypeMeta] = {
    "vlm": EngineTypeMeta(
        category="vlm",
        display_name="VLM / LLM",
        icon="vlm",
        description="Visual Language Models and Large Language Models for document understanding",
        default_provider_type="openai_compatible",
        supported_input_types=["image/*"],
        response_formats=["openai_chat", "node_output"],
        allow_multiple_models=True,
    ),
    "ocr": EngineTypeMeta(
        category="ocr",
        display_name="OCR",
        icon="ocr",
        description="Optical Character Recognition engines",
        default_provider_type="engine_service",
        supported_input_types=["image/*"],
        response_formats=["node_output", "simple_blocks", "hocr", "raw_text"],
        allow_multiple_models=False,
    ),
    "text": EngineTypeMeta(
        category="text",
        display_name="Text Engine",
        icon="text",
        description="Plain text and HTML parsing engines",
        default_provider_type="engine_service",
        supported_input_types=["text/plain", "text/html"],
        response_formats=["node_output", "raw_text"],
        allow_multiple_models=False,
    ),
    "markitdown": EngineTypeMeta(
        category="markitdown",
        display_name="MarkItDown",
        icon="markitdown",
        description="Multi-format document conversion (PDF, DOCX, XLSX)",
        default_provider_type="engine_service",
        supported_input_types=[
            "application/pdf",
            "application/vnd.openxmlformats-offxmlformats.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ],
        response_formats=["node_output", "raw_text"],
        allow_multiple_models=False,
    ),
    "docling": EngineTypeMeta(
        category="docling",
        display_name="Docling",
        icon="docling",
        description="IBM Docling document conversion engine (PDF, DOCX, PPTX, HTML, images)",
        default_provider_type="engine_service",
        supported_input_types=["application/pdf", "text/plain", "text/html"],
        response_formats=["node_output"],
        allow_multiple_models=False,
    ),
    "layout_detection": EngineTypeMeta(
        category="layout_detection",
        display_name="Layout Detection",
        icon="layout_detection",
        description="Document layout analysis and structure detection",
        default_provider_type="engine_service",
        supported_input_types=["image/*"],
        response_formats=["node_output"],
        allow_multiple_models=False,
    ),
    "image_enhancement": EngineTypeMeta(
        category="image_enhancement",
        display_name="Image Enhancement",
        icon="image_enhancement",
        description="Image quality enhancement and preprocessing",
        default_provider_type="engine_service",
        supported_input_types=["image/*"],
        response_formats=["node_output"],
        allow_multiple_models=False,
    ),
    "image_rotation": EngineTypeMeta(
        category="image_rotation",
        display_name="Image Rotation",
        icon="image_rotation",
        description="Image rotation and orientation correction",
        default_provider_type="engine_service",
        supported_input_types=["image/*"],
        response_formats=["node_output"],
        allow_multiple_models=False,
    ),
}


def get_engine_meta(category: str) -> EngineTypeMeta | None:
    """Get ENGINE type metadata by category. Returns None if not found."""
    return ENGINE_TYPES.get(category)


def get_all_categories() -> list[str]:
    """Get all registered ENGINE category identifiers."""
    return list(ENGINE_TYPES.keys())


def get_category_defaults(category: str) -> dict:
    """Return default values for a provider based on its ENGINE category."""
    engine = ENGINE_TYPES.get(category)
    if not engine:
        return {}

    defaults: dict[str, str] = {
        "provider_type": engine.default_provider_type,
        "response_format": engine.response_formats[0],
    }

    if engine.default_provider_type == "openai_compatible":
        defaults["response_format"] = "openai_chat"

    return defaults
