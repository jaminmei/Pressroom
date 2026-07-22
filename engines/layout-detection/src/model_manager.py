"""
Layout Detection Model Manager

Manages model loading, configuration, and inference for layout detection.
Supports multiple models with different layout type mappings.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default mapping table path
DEFAULT_MAPPING_PATH = Path(__file__).parent.parent / "models" / "mapping_table.json"


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    model_id: str
    model_file: str
    display_name: str
    layout_types: list[str]
    language: str


class LayoutModelManager:
    """Manages layout detection models and their configurations."""

    def __init__(self, mapping_path: Optional[Path] = None):
        """
        Initialize the model manager.

        Args:
            mapping_path: Path to the mapping table JSON file.
        """
        self.mapping_path = mapping_path or DEFAULT_MAPPING_PATH
        self.mapping_data: dict[str, Any] = {}
        self._load_mapping_table()

    def _load_mapping_table(self) -> None:
        """Load the model mapping table from JSON file."""
        if self.mapping_path.exists():
            try:
                with open(self.mapping_path, encoding="utf-8") as f:
                    self.mapping_data = json.load(f)
                logger.info("Loaded layout model mapping table")
            except Exception as e:
                logger.error("Layout model mapping load failed error_type=%s", type(e).__name__)
                self._use_default_mapping()
        else:
            logger.warning("Layout model mapping table not found; using defaults")
            self._use_default_mapping()

    def _use_default_mapping(self) -> None:
        """Use default PPStructure mapping."""
        self.mapping_data = {
            "models": {
                "ppstructure_v2": {
                    "display_name": "PP-StructureV2",
                    "supported_languages": ["ch", "en"],
                    "model_files": {
                        "picodet_lcnet_x1_0": {
                            "display_name": "PicoDet-LCNet x1.0",
                            "layout_types": {
                                "ch": [
                                    "Text",
                                    "Title",
                                    "Figure",
                                    "Figure_caption",
                                    "Table",
                                    "Table_caption",
                                    "Header",
                                    "Footer",
                                    "Reference",
                                    "Equation",
                                ],
                                "en": [
                                    "Text",
                                    "Title",
                                    "Figure",
                                    "Table",
                                    "Caption",
                                    "Header",
                                    "Footer",
                                    "Reference",
                                    "Equation",
                                ],
                            },
                        }
                    },
                }
            },
            "default_model": "ppstructure_v2",
            "default_model_file": "picodet_lcnet_x1_0",
            "default_language": "ch",
        }

    def get_available_models(self) -> list[dict[str, Any]]:
        """
        Get list of available models.

        Returns:
            List of model info dicts with id, display_name, model_files.
        """
        models = []
        for model_id, model_data in self.mapping_data.get("models", {}).items():
            model_files = []
            for file_id, file_data in model_data.get("model_files", {}).items():
                model_files.append(
                    {
                        "id": file_id,
                        "display_name": file_data.get("display_name", file_id),
                        "description": file_data.get("description", ""),
                    }
                )

            models.append(
                {
                    "id": model_id,
                    "display_name": model_data.get("display_name", model_id),
                    "description": model_data.get("description", ""),
                    "supported_languages": model_data.get("supported_languages", []),
                    "model_files": model_files,
                }
            )

        return models

    def get_layout_types(self, model_id: str, model_file: str, language: str = "ch") -> list[str]:
        """
        Get supported layout types for a specific model configuration.

        Args:
            model_id: Model identifier (e.g., "ppstructure_v2")
            model_file: Model file identifier (e.g., "picodet_lcnet_x1_0")
            language: Language code

        Returns:
            List of supported layout type strings.
        """
        try:
            # Resolve aliases before lookup
            model_id = self._resolve_model_id(model_id)
            model_file, lang_hint = self._resolve_model_file(model_file)
            if lang_hint:
                language = lang_hint

            model = self.mapping_data["models"][model_id]
            model_file_data = model["model_files"][model_file]
            layout_types_map = model_file_data.get("layout_types", {})

            # Try exact language match, then "universal", then first available
            if language in layout_types_map:
                return layout_types_map[language]
            elif "universal" in layout_types_map:
                return layout_types_map["universal"]
            elif layout_types_map:
                return list(layout_types_map.values())[0]

            return []

        except KeyError as e:
            logger.error("Layout model configuration not found error_type=%s", type(e).__name__)
            return []

    # Alias mapping: node_registry values → mapping_table keys
    MODEL_ID_ALIASES: dict[str, str] = {
        "ppstructure": "ppstructure_v2",
    }

    # When node_registry sends language codes as model_file (e.g. "en", "ch"),
    # resolve them to the actual model file key in mapping_table.json.
    MODEL_FILE_ALIASES: dict[str, str] = {
        "en": "picodet_lcnet_x1_0",
        "ch": "picodet_lcnet_x1_0",
    }

    def _resolve_model_id(self, model_id: str) -> str:
        """Resolve model_id alias to the canonical key in mapping_table."""
        resolved = self.MODEL_ID_ALIASES.get(model_id, model_id)
        if resolved != model_id:
            logger.info("Resolved model_id alias: '%s' -> '%s'", model_id, resolved)
        return resolved

    def _resolve_model_file(self, model_file: str) -> tuple[str, str | None]:
        """Resolve model_file alias.

        If the caller passed a language code (e.g. "en") as model_file,
        return the actual model file key and preserve the language.

        Returns:
            (resolved_model_file, language_hint_or_None)
        """
        if model_file in self.MODEL_FILE_ALIASES:
            resolved = self.MODEL_FILE_ALIASES[model_file]
            logger.info(
                "Resolved model_file alias: '%s' -> '%s' (treating '%s' as language hint)",
                model_file,
                resolved,
                model_file,
            )
            return resolved, model_file
        return model_file, None

    def get_model_config(
        self,
        model_id: Optional[str] = None,
        model_file: Optional[str] = None,
        language: Optional[str] = None,
    ) -> ModelConfig:
        """
        Get model configuration with defaults.

        Args:
            model_id: Model identifier (uses default if not provided)
            model_file: Model file identifier (uses default if not provided)
            language: Language code (uses default if not provided)

        Returns:
            ModelConfig with all settings resolved.
        """
        # Use defaults from mapping table
        model_id = model_id or self.mapping_data.get("default_model", "ppstructure_v2")
        model_file = model_file or self.mapping_data.get("default_model_file", "picodet_lcnet_x1_0")
        language = language or self.mapping_data.get("default_language", "ch")

        # Resolve aliases (node_registry may send different names)
        model_id = self._resolve_model_id(model_id)
        model_file, lang_hint = self._resolve_model_file(model_file)
        if lang_hint:
            language = lang_hint

        # Get model info
        try:
            model_data = self.mapping_data["models"][model_id]
            file_data = model_data["model_files"][model_file]
            model_display_name = model_data.get("display_name", model_id)
            file_display_name = file_data.get("display_name", model_file)
            display_name = f"{model_display_name} - {file_display_name}"
        except KeyError:
            display_name = f"{model_id}/{model_file}"

        layout_types = self.get_layout_types(model_id, model_file, language)
        # Provide default: if layout_types is empty
        default_layout_types = ["Text", "Title", "Figure", "Table", "Header", "Footer"]
        logger.debug(
            "get_model_config: layout_types from mapping=%s, default=%s",
            layout_types,
            default_layout_types,
        )

        return ModelConfig(
            model_id=model_id,
            model_file=model_file,
            display_name=display_name,
            layout_types=layout_types or default_layout_types,
            language=language,
        )


# Singleton instance
_manager: Optional[LayoutModelManager] = None


def get_model_manager() -> LayoutModelManager:
    """Get or create the singleton model manager."""
    global _manager
    if _manager is None:
        _manager = LayoutModelManager()
    return _manager
