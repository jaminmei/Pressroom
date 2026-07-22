"""
app/providers/seed.py
---------------------
Seed the provider registry with default providers and models.

Call ``seed_default_providers(store)`` once at application startup.
The function is idempotent: it skips seeding entirely when any provider
row already exists in the database.
"""

from __future__ import annotations

import logging

from app.providers.models import ModelProviderCreate, ProviderScope
from app.providers.store import ProviderStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static seed data
# ---------------------------------------------------------------------------

SEED_PROVIDERS: list[dict] = [
    {
        "name": "RapidOCR",
        "provider_type": "engine_service",
        "engine_category": "ocr",
        "base_url": "http://ocr-engine:8080",
        "health_url": "http://ocr-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
    {
        "name": "Rule-Based Parser",
        "provider_type": "engine_service",
        "engine_category": "text",
        "base_url": "http://text-engine:8080",
        "health_url": "http://text-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
    {
        "name": "MarkItDown",
        "provider_type": "engine_service",
        "engine_category": "markitdown",
        "base_url": "http://markitdown-engine:8080",
        "health_url": "http://markitdown-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
    {
        "name": "Docling",
        "provider_type": "engine_service",
        "engine_category": "docling",
        "base_url": "http://docling-engine:8080",
        "health_url": "http://docling-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
    {
        "name": "PP-Structure (English)",
        "provider_type": "engine_service",
        "engine_category": "layout_detection",
        "base_url": "http://layout-detection-engine:8080",
        "health_url": "http://layout-detection-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": False,
        "is_enabled": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "selected_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["Text", "Title", "Table", "Figure", "List"],
                        "enum_metadata": {
                            "Text": {"display_name": "Text (文本)"},
                            "Title": {"display_name": "Title (标题)"},
                            "Table": {"display_name": "Table (表格)"},
                            "Figure": {"display_name": "Figure (图片)"},
                            "List": {"display_name": "List (列表)"},
                        },
                    },
                    "title": "Selected Layout Types",
                    "description": "Select which layout types to output.",
                    "default": [],
                },
            },
            "required": [],
        },
    },
    {
        "name": "PP-Structure (Chinese)",
        "provider_type": "engine_service",
        "engine_category": "layout_detection",
        "base_url": "http://layout-detection-engine:8080",
        "health_url": "http://layout-detection-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "selected_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "Text",
                            "Title",
                            "Figure",
                            "Table",
                            "Header",
                            "Footer",
                            "Figure_caption",
                            "Table_caption",
                            "Reference",
                            "Equation",
                        ],
                        "enum_metadata": {
                            "Text": {"display_name": "Text (文本)"},
                            "Title": {"display_name": "Title (标题)"},
                            "Figure": {"display_name": "Figure (图片)"},
                            "Table": {"display_name": "Table (表格)"},
                            "Header": {"display_name": "Header (页眉)"},
                            "Footer": {"display_name": "Footer (页脚)"},
                            "Figure_caption": {"display_name": "Figure Caption (图片说明)"},
                            "Table_caption": {"display_name": "Table Caption (表格说明)"},
                            "Reference": {"display_name": "Reference (参考文献)"},
                            "Equation": {"display_name": "Equation (公式)"},
                        },
                    },
                    "title": "Selected Layout Types",
                    "description": "Select which layout types to output.",
                    "default": [],
                },
            },
            "required": [],
        },
    },
    {
        "name": "OpenCV Enhancement",
        "provider_type": "engine_service",
        "engine_category": "image_enhancement",
        "base_url": "http://image-enhancement-engine:8080",
        "health_url": "http://image-enhancement-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
    {
        "name": "OpenCV Rotation",
        "provider_type": "engine_service",
        "engine_category": "image_rotation",
        "base_url": "http://image-rotation-engine:8080",
        "health_url": "http://image-rotation-engine:8080/health",
        "response_format": "node_output",
        "auth_type": "none",
        "is_default": True,
        "is_enabled": True,
    },
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def seed_default_providers(store: ProviderStore) -> int:
    """Seed default engine_service providers if the database is empty.

    Idempotent: returns 0 if any providers already exist. This means:

    - If you manually delete *all* providers and restart, the full seed
      set is re-created.
    - If even one provider remains (including manually created ones),
      seeding is skipped entirely.

    Note: ``openai_compatible`` providers (VLM model services) are NOT seeded.
    Users create those manually via the Settings UI, including adding
    deployment names (models) themselves.

    Returns:
        int: Number of providers seeded (0 if skipped).
    """
    existing = store.list_providers(enabled_only=False)
    if len(existing) > 0:
        logger.debug(
            "seed_default_providers: %d provider(s) already exist, skipping.",
            len(existing),
        )
        return 0

    for provider_data in SEED_PROVIDERS:
        create_data = ModelProviderCreate(**provider_data, scope=ProviderScope.system)
        row = store.create_provider(create_data)
        logger.debug("Seeded provider id=%s", row.id)

    logger.info("seed_default_providers: seeded %d providers.", len(SEED_PROVIDERS))
    return len(SEED_PROVIDERS)
