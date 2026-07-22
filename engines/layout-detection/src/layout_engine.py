"""
Layout Detection Engine

Performs document layout analysis using PPStructure or other models.
Returns detected regions with bounding boxes and types.
"""

import base64
import logging
from typing import Any, Optional

import cv2
import numpy as np
from PIL import Image
from src.model_manager import ModelConfig, get_model_manager

logger = logging.getLogger(__name__)


class LayoutEngine:
    """Layout detection engine using PPStructure."""

    def __init__(
        self,
        model_config: Optional[ModelConfig] = None,
        use_gpu: bool = False,
        show_log: bool = False,
    ):
        """
        Initialize the layout detection engine.

        Args:
            model_config: Model configuration (uses default if not provided)
            use_gpu: Whether to use GPU acceleration
            show_log: Whether to show engine logs
        """
        self.model_config = model_config or get_model_manager().get_model_config()
        self.use_gpu = use_gpu
        self.show_log = show_log

        # Initialize PPStructure
        self._init_engine()

    def _init_engine(self) -> None:
        """Initialize the PPStructure engine."""
        logger.info("Initializing Layout Detection engine gpu=%s", self.use_gpu)

        try:
            from paddleocr import PPStructure

            # Initialize PPStructure for layout analysis only
            self.engine = PPStructure(
                use_gpu=self.use_gpu,
                lang=self.model_config.language,
                show_log=self.show_log,
                table=False,  # Disable table recognition (we only need layout)
                ocr=False,  # Disable OCR (we only need layout)
                structure_version="PP-StructureV2",
                recovery=False,
            )

            logger.info("Layout Detection engine initialized successfully")

        except Exception as err:
            logger.error("PPStructure initialization failed error_type=%s", type(err).__name__)
            raise RuntimeError(f"PPStructure initialization failed: {err}") from err

    def detect_layout(
        self,
        image: np.ndarray,
        selected_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Detect layout regions in an image.

        Args:
            image: Input image as numpy array (BGR format)
            selected_types: Optional filter for specific layout types

        Returns:
            List of detected regions with bbox, type, confidence.
        """
        try:
            # Run PPStructure
            result = self.engine(image)

            logger.info("PPStructure completed item_count=%d", len(result))

            regions: list[dict[str, Any]] = []
            valid_types = selected_types or self.model_config.layout_types

            for idx, item in enumerate(result):
                # Extract bounding box
                bbox = item.get("bbox")
                if bbox is None:
                    continue

                # bbox format: [x1, y1, x2, y2]
                x1, y1, x2, y2 = bbox
                region_bbox = {
                    "x": int(x1),
                    "y": int(y1),
                    "width": int(x2 - x1),
                    "height": int(y2 - y1),
                }

                # Get region type (normalize to match our types)
                region_type_raw = item.get("type", "text")
                region_type = self._normalize_layout_type(region_type_raw)

                # Filter by selected types
                if selected_types and region_type not in valid_types:
                    continue

                # Get confidence
                confidence = item.get("score", 0.9)
                if isinstance(confidence, (int, float)):
                    confidence = float(confidence)
                else:
                    confidence = 0.9

                regions.append(
                    {
                        "id": f"layout_{idx}",
                        "type": region_type,
                        "bbox": region_bbox,
                        "confidence": round(confidence, 4),
                    }
                )

            logger.info(
                "Layout detection completed region_count=%d raw_item_count=%d",
                len(regions),
                len(result),
            )
            return regions

        except Exception as err:
            logger.error("Layout detection failed error_type=%s", type(err).__name__)
            raise RuntimeError(f"Layout detection failed: {err}") from err

    def _normalize_layout_type(self, raw_type: str) -> str:
        """Normalize layout type from engine output to standard format."""
        # Mapping from PPStructure output types to our standard types
        type_mapping = {
            "text": "Text",
            "title": "Title",
            "figure": "Figure",
            "figure_caption": "Figure_caption",
            "table": "Table",
            "table_caption": "Table_caption",
            "header": "Header",
            "footer": "Footer",
            "reference": "Reference",
            "equation": "Equation",
            "list": "List",
            "caption": "Caption",
        }
        normalized = type_mapping.get(raw_type.lower(), raw_type.capitalize())
        return normalized

    def detect_from_file(
        self,
        file_path: str,
        selected_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Detect layout regions from an image file."""
        image = cv2.imread(file_path)
        if image is None:
            raise ValueError(f"Failed to load image: {file_path}")
        return self.detect_layout(image, selected_types)

    def detect_from_base64(
        self,
        base64_data: str,
        selected_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Detect layout regions from base64 encoded image."""
        image_bytes = base64.b64decode(base64_data)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Failed to decode base64 image")

        return self.detect_layout(image, selected_types)

    def detect_from_pil(
        self,
        pil_image: Image.Image,
        selected_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Detect layout regions from a PIL Image."""
        # Convert PIL to OpenCV format (RGB -> BGR)
        image_array = np.array(pil_image)
        if image_array.ndim == 3:
            image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        else:
            image = cv2.cvtColor(image_array, cv2.COLOR_GRAY2BGR)

        return self.detect_layout(image, selected_types)

    def get_supported_types(self) -> list[str]:
        """Get list of supported layout types for current configuration."""
        return self.model_config.layout_types
