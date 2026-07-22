"""
Image Enhancement Engine

Provides document image enhancement capabilities:
- CLAHE contrast enhancement
- Denoising
- Sharpening
- Binarization
- Deskewing
"""

import base64
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class EnhancementType(str, Enum):
    """Available enhancement types."""

    CLAHE = "clahe"
    DENOISE = "denoise"
    SHARPEN = "sharpen"
    BINARIZE = "binarize"
    DESKEW = "deskew"
    AUTO_CONTRAST = "auto_contrast"
    REMOVE_SHADOW = "remove_shadow"


@dataclass
class EnhancementConfig:
    """Configuration for image enhancement."""

    clahe: bool = True
    clahe_clip_limit: float = 2.0
    clahe_tile_size: tuple[int, int] = (8, 8)

    denoise: bool = False
    denoise_strength: float = 10.0

    sharpen: bool = False
    sharpen_strength: float = 1.0

    binarize: bool = False
    binarize_method: str = "otsu"  # "otsu" or "adaptive"

    deskew: bool = False

    auto_contrast: bool = False

    remove_shadow: bool = False

    output_format: str = "png"  # "png" or "jpeg"
    jpeg_quality: int = 95


class ImageEnhancementEngine:
    """Image enhancement engine for document preprocessing."""

    def __init__(self, default_config: Optional[EnhancementConfig] = None):
        """
        Initialize the enhancement engine.

        Args:
            default_config: Default enhancement configuration.
        """
        self.default_config = default_config or EnhancementConfig()
        logger.info("Image Enhancement engine initialized")

    def enhance(
        self,
        image: np.ndarray,
        config: Optional[EnhancementConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """
        Apply enhancement to an image.

        Args:
            image: Input image as numpy array (BGR format)
            config: Enhancement configuration (uses default if not provided)

        Returns:
            Tuple of (enhanced_image, enhancement_info).
        """
        cfg = config or self.default_config
        enhanced = image.copy()
        applied_enhancements: list[str] = []

        # Convert to grayscale for some operations
        if len(image.shape) == 3:
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            pass

        # 1. Auto Contrast
        if cfg.auto_contrast:
            enhanced = self._apply_auto_contrast(enhanced)
            applied_enhancements.append("auto_contrast")

        # 2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
        if cfg.clahe:
            enhanced = self._apply_clahe(enhanced, cfg)
            applied_enhancements.append("clahe")

        # 3. Denoise
        if cfg.denoise:
            enhanced = self._apply_denoise(enhanced, cfg)
            applied_enhancements.append("denoise")

        # 4. Sharpen
        if cfg.sharpen:
            enhanced = self._apply_sharpen(enhanced, cfg)
            applied_enhancements.append("sharpen")

        # 5. Remove shadow
        if cfg.remove_shadow:
            enhanced = self._remove_shadow(enhanced)
            applied_enhancements.append("remove_shadow")

        # 6. Deskew
        if cfg.deskew:
            enhanced, angle = self._deskew(enhanced)
            applied_enhancements.append(f"deskew({angle:.2f}°)")

        # 7. Binarize (should be last)
        if cfg.binarize:
            enhanced = self._apply_binarize(enhanced, cfg)
            applied_enhancements.append("binarize")

        info = {
            "applied_enhancements": applied_enhancements,
            "original_shape": image.shape,
            "output_shape": enhanced.shape,
        }

        logger.info(f"Applied enhancements: {applied_enhancements}")
        return enhanced, info

    def _apply_auto_contrast(self, image: np.ndarray) -> np.ndarray:
        """Apply auto contrast (stretch histogram to full range)."""
        if len(image.shape) == 3:
            # Process each channel
            result = np.zeros_like(image)
            for i in range(3):
                channel = image[:, :, i]
                min_val = np.min(channel)
                max_val = np.max(channel)
                if max_val > min_val:
                    result[:, :, i] = ((channel - min_val) * 255 / (max_val - min_val)).astype(
                        np.uint8
                    )
                else:
                    result[:, :, i] = channel
            return result
        else:
            min_val = np.min(image)
            max_val = np.max(image)
            if max_val > min_val:
                return ((image - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
            return image

    def _apply_clahe(self, image: np.ndarray, cfg: EnhancementConfig) -> np.ndarray:
        """Apply CLAHE contrast enhancement."""
        clahe = cv2.createCLAHE(
            clipLimit=cfg.clahe_clip_limit,
            tileGridSize=cfg.clahe_tile_size,
        )

        if len(image.shape) == 3:
            # Convert to LAB color space
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        else:
            return clahe.apply(image)

    def _apply_denoise(self, image: np.ndarray, cfg: EnhancementConfig) -> np.ndarray:
        """Apply denoising."""
        strength = int(cfg.denoise_strength)

        if len(image.shape) == 3:
            return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)
        else:
            return cv2.fastNlMeansDenoising(image, None, strength, 7, 21)

    def _apply_sharpen(self, image: np.ndarray, cfg: EnhancementConfig) -> np.ndarray:
        """Apply sharpening using unsharp mask."""
        strength = cfg.sharpen_strength

        if len(image.shape) == 3:
            blurred = cv2.GaussianBlur(image, (0, 0), 3)
            sharpened = cv2.addWeighted(image, 1 + strength, blurred, -strength, 0)
        else:
            blurred = cv2.GaussianBlur(image, (0, 0), 3)
            sharpened = cv2.addWeighted(image, 1 + strength, blurred, -strength, 0)

        return np.clip(sharpened, 0, 255).astype(np.uint8)

    def _apply_binarize(self, image: np.ndarray, cfg: EnhancementConfig) -> np.ndarray:
        """Apply binarization."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        if cfg.binarize_method == "adaptive":
            return cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
        else:  # otsu
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary

    def _remove_shadow(self, image: np.ndarray) -> np.ndarray:
        """Remove shadows using morphological operations."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Dilate to get background
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
        background = cv2.dilate(gray, kernel)

        # Subtract background
        diff = cv2.absdiff(gray, background)

        # Normalize
        _, result = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        if len(image.shape) == 3:
            return cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        return result

    def _deskew(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """Deskew image using Hough transform or projection profile."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Use Hough Line Transform to detect text lines
        lines = cv2.HoughLinesP(
            binary, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
        )

        if lines is None or len(lines) == 0:
            return image, 0.0

        # Calculate angles
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 != 0:
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Only consider near-horizontal lines
                if abs(angle) < 45:
                    angles.append(angle)

        if not angles:
            return image, 0.0

        # Use median angle
        median_angle = np.median(angles)

        # Only rotate if angle is significant
        if abs(median_angle) < 0.5:
            return image, 0.0

        # Rotate image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(
            image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )

        return rotated, median_angle

    def enhance_from_file(
        self,
        file_path: str,
        config: Optional[EnhancementConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Enhance image from file."""
        image = cv2.imread(file_path)
        if image is None:
            raise ValueError(f"Failed to load image: {file_path}")
        return self.enhance(image, config)

    def enhance_from_base64(
        self,
        base64_data: str,
        config: Optional[EnhancementConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Enhance image from base64 encoded data."""
        image_bytes = base64.b64decode(base64_data)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Failed to decode base64 image")

        return self.enhance(image, config)

    def encode_to_base64(
        self,
        image: np.ndarray,
        output_format: str = "png",
        jpeg_quality: int = 95,
    ) -> str:
        """Encode image to base64."""
        if output_format.lower() == "jpeg":
            encode_param = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            ext = ".jpg"
        else:
            encode_param = []
            ext = ".png"

        success, encoded = cv2.imencode(ext, image, encode_param)
        if not success:
            raise ValueError("Failed to encode image")

        return base64.b64encode(encoded.tobytes()).decode("ascii")
