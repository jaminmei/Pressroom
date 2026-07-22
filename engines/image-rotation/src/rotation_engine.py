"""
Image Rotation Engine

Provides document image rotation capabilities:
- Fixed angle rotation (90°, 180°, 270°)
- Custom angle rotation
- Auto-rotation based on text orientation detection
"""

import base64
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class RotationMode(str, Enum):
    """Rotation mode options."""

    FIXED = "fixed"  # Fixed angle: 90, 180, 270
    CUSTOM = "custom"  # Custom angle
    AUTO = "auto"  # Auto-detect from text orientation
    AUTO_UPRIGHT = "auto_upright"  # Auto-rotate to upright (0° or 180°)


@dataclass
class RotationConfig:
    """Configuration for image rotation."""

    mode: RotationMode = RotationMode.FIXED
    angle: float = 0.0  # For FIXED or CUSTOM mode
    auto_detect_method: str = "text_lines"  # For AUTO mode: "text_lines", "hough", "contours"
    expand_canvas: bool = False  # Expand canvas to fit rotated image
    fill_color: tuple[int, int, int] = (255, 255, 255)  # Fill color for expanded areas
    output_format: str = "png"
    jpeg_quality: int = 95


class ImageRotationEngine:
    """Image rotation engine for document preprocessing."""

    def __init__(self, default_config: Optional[RotationConfig] = None):
        """
        Initialize the rotation engine.

        Args:
            default_config: Default rotation configuration.
        """
        self.default_config = default_config or RotationConfig()
        logger.info("Image Rotation engine initialized")

    def rotate(
        self,
        image: np.ndarray,
        config: Optional[RotationConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """
        Rotate an image.

        Args:
            image: Input image as numpy array (BGR format)
            config: Rotation configuration (uses default if not provided)

        Returns:
            Tuple of (rotated_image, rotation_info).
        """
        cfg = config or self.default_config
        rotated = image.copy()
        applied_angle = 0.0

        if cfg.mode == RotationMode.FIXED:
            # Fixed 90° rotations
            if cfg.angle == 90:
                rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
                applied_angle = 90.0
            elif cfg.angle == 180:
                rotated = cv2.rotate(image, cv2.ROTATE_180)
                applied_angle = 180.0
            elif cfg.angle == 270:
                rotated = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
                applied_angle = 270.0
            else:
                logger.warning(f"Invalid fixed angle {cfg.angle}, using 0")

        elif cfg.mode == RotationMode.CUSTOM:
            # Custom angle rotation
            rotated, applied_angle = self._rotate_custom(image, cfg.angle, cfg)

        elif cfg.mode == RotationMode.AUTO:
            # Auto-detect rotation angle
            detected_angle = self._detect_rotation_angle(image, cfg.auto_detect_method)
            if abs(detected_angle) > 0.5:  # Only rotate if significant
                rotated, applied_angle = self._rotate_custom(image, detected_angle, cfg)
            else:
                applied_angle = 0.0

        elif cfg.mode == RotationMode.AUTO_UPRIGHT:
            # Auto-rotate to upright (detect if upside down)
            detected_angle = self._detect_upright_angle(image)
            if detected_angle != 0:
                rotated = cv2.rotate(image, cv2.ROTATE_180)
                applied_angle = 180.0
            else:
                applied_angle = 0.0

        info = {
            "mode": cfg.mode.value,
            "applied_angle": applied_angle,
            "original_shape": list(image.shape),
            "output_shape": list(rotated.shape),
            "expand_canvas": cfg.expand_canvas,
        }

        logger.info(f"Applied rotation: {applied_angle}° (mode: {cfg.mode.value})")
        return rotated, info

    def _rotate_custom(
        self,
        image: np.ndarray,
        angle: float,
        config: RotationConfig,
    ) -> tuple[np.ndarray, float]:
        """Rotate image by custom angle."""
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)

        # Get rotation matrix
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

        if config.expand_canvas:
            # Calculate new image size to fit rotated image
            cos = np.abs(matrix[0, 0])
            sin = np.abs(matrix[0, 1])
            new_w = int((h * sin) + (w * cos))
            new_h = int((h * cos) + (w * sin))

            # Adjust the rotation matrix
            matrix[0, 2] += (new_w / 2) - center[0]
            matrix[1, 2] += (new_h / 2) - center[1]

            # Perform rotation
            rotated = cv2.warpAffine(
                image,
                matrix,
                (new_w, new_h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=config.fill_color,
            )
        else:
            # Standard rotation (may crop corners)
            rotated = cv2.warpAffine(
                image,
                matrix,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=config.fill_color,
            )

        return rotated, angle

    def _detect_rotation_angle(
        self,
        image: np.ndarray,
        method: str = "text_lines",
    ) -> float:
        """
        Detect rotation angle of the image.

        Args:
            image: Input image
            method: Detection method

        Returns:
            Detected angle in degrees.
        """
        if method == "hough":
            return self._detect_angle_hough(image)
        elif method == "contours":
            return self._detect_angle_contours(image)
        else:  # text_lines (default)
            return self._detect_angle_text_lines(image)

    def _detect_angle_text_lines(self, image: np.ndarray) -> float:
        """Detect angle using text line detection."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Detect lines using HoughLinesP
        lines = cv2.HoughLinesP(
            binary, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
        )

        if lines is None or len(lines) < 5:
            return 0.0

        # Calculate angles
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 != 0:
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Only consider near-horizontal lines
                if abs(angle) < 45:
                    angles.append(angle)

        if len(angles) < 3:
            return 0.0

        # Use median angle
        return float(np.median(angles))

    def _detect_angle_hough(self, image: np.ndarray) -> float:
        """Detect angle using Hough Line Transform."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # Hough Line Transform
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

        if lines is None or len(lines) < 5:
            return 0.0

        angles = []
        for line in lines:
            rho, theta = line[0]
            angle = np.degrees(theta) - 90  # Convert to rotation angle
            if abs(angle) < 45:
                angles.append(angle)

        if len(angles) < 3:
            return 0.0

        return float(np.median(angles))

    def _detect_angle_contours(self, image: np.ndarray) -> float:
        """Detect angle using minimum area rectangle on contours."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Find contours
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return 0.0

        # Get all contour points
        all_points = np.vstack(contours)

        # Minimum area rectangle
        rect = cv2.minAreaRect(all_points)
        (_, (w, h), angle) = rect

        # Normalize angle
        if w < h:
            angle = angle + 90

        # Normalize to -45 to 45 range
        while angle > 45:
            angle -= 90
        while angle < -45:
            angle += 90

        return angle

    def _detect_upright_angle(self, image: np.ndarray) -> float:
        """
        Detect if image is upside down.

        Returns:
            0 if upright, 180 if upside down.
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Get upper and lower halves
        h = gray.shape[0]
        upper = gray[: h // 2, :]
        lower = gray[h // 2 :, :]

        # Count text density in each half
        _, upper_binary = cv2.threshold(upper, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, lower_binary = cv2.threshold(lower, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        upper_density = np.sum(upper_binary > 0) / upper_binary.size
        lower_density = np.sum(lower_binary > 0) / lower_binary.size

        # Documents typically have more content at the top (headers, titles)
        # If lower half has more content, might be upside down
        # This is a heuristic and may not always work

        # Also check for typical document patterns
        # Text lines should be horizontal, more dense at top for title/header

        # Simple heuristic: if significantly more content at bottom, consider upside down
        if lower_density > upper_density * 1.5:
            return 180.0

        return 0.0

    def rotate_from_file(
        self,
        file_path: str,
        config: Optional[RotationConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Rotate image from file."""
        image = cv2.imread(file_path)
        if image is None:
            raise ValueError(f"Failed to load image: {file_path}")
        return self.rotate(image, config)

    def rotate_from_base64(
        self,
        base64_data: str,
        config: Optional[RotationConfig] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Rotate image from base64 encoded data."""
        image_bytes = base64.b64decode(base64_data)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Failed to decode base64 image")

        return self.rotate(image, config)

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
