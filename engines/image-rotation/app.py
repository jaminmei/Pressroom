"""
Image Rotation Engine Service

API 規格：
- GET /health: 健康檢查
- GET /config: 获取可用的旋转选项
- POST /process: 处理图片，返回旋转后的图片

Output format (NodeOutput envelope):
{
    "text": null,
    "binary": [{"ref": "", "data": "<base64>", "mime_type": "image/png", "size_bytes": 12345}],
    "structured": null,
    "metadata": {
        "processing_time_ms": 123,
        "applied_angle": 90.0,
        "mode": "fixed",
        "original_shape": [1000, 800, 3],
        "output_shape": [800, 1000, 3]
    }
}
"""

import base64
import logging
import time
from pathlib import Path
from typing import Optional

import cv2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.rotation_engine import ImageRotationEngine, RotationConfig, RotationMode

# MIME type mapping for common output formats
_MIME_MAP = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _shape_to_dimensions(shape) -> dict:
    """Convert an image shape tuple/list to BinaryRef dimensions metadata."""
    height = int(shape[0]) if len(shape) > 0 else 0
    width = int(shape[1]) if len(shape) > 1 else 0
    dimensions = {"height": height, "width": width}
    if len(shape) > 2:
        dimensions["channels"] = int(shape[2])
    return dimensions


app = FastAPI(
    title="Image Rotation Engine Service",
    description="Document image rotation for preprocessing",
    version="1.0.0",
)

# Global engine instance
rotation_engine: Optional[ImageRotationEngine] = None


def get_rotation_engine() -> ImageRotationEngine:
    """Get or initialize rotation engine."""
    global rotation_engine
    if rotation_engine is None:
        logger.info("Initializing Image Rotation engine...")
        rotation_engine = ImageRotationEngine()
        logger.info("Image Rotation engine initialized successfully")
    return rotation_engine


# === Request/Response Models ===


class NodeOutputInput(BaseModel):
    """Input slot value matching NodeOutput schema."""

    text: Optional[str] = None
    binary: list[dict] = []
    structured: Optional[dict] = None
    metadata: dict = {}


class NewProcessRequest(BaseModel):
    """Named-input request format from EngineClient."""

    inputs: dict[str, NodeOutputInput]
    config: dict = {}


class HealthResponse(BaseModel):
    """健康檢查回應"""

    status: str
    engine: str
    version: str


class ConfigSchemaResponse(BaseModel):
    """Configuration schema response"""

    engine_type: str
    version: str
    config_schema: dict


# === API Endpoints ===


@app.get("/health", response_model=HealthResponse)
async def health():
    """Basic health check"""
    return HealthResponse(
        status="healthy",
        engine="image-rotation",
        version="1.0.0",
    )


@app.get("/config", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """Return available rotation options"""
    return ConfigSchemaResponse(
        engine_type="image-rotation",
        version="1.0.0",
        config_schema={
            "type": "object",
            "properties": {
                "angle": {
                    "type": "number",
                    "title": "Rotation Angle",
                    "description": (
                        "Rotation angle in degrees (clockwise). Positive values rotate "
                        "clockwise, negative rotates counter-clockwise."
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
            "required": [],
        },
    )


@app.post("/process")
async def process(request: NewProcessRequest):
    """
    Rotate image.

    Accepts named-input format (inputs.image) and returns a NodeOutput envelope
    with the rotated image saved as a temp file reference in binary.
    """
    start_time = time.time()

    try:
        engine = get_rotation_engine()

        # Parse configuration
        config_dict = request.config or {}

        # Determine mode
        mode_str = config_dict.get("mode", "fixed")
        mode = RotationMode(mode_str)

        # Get angle based on mode
        if mode == RotationMode.FIXED:
            angle = float(config_dict.get("angle", 0))
        elif mode == RotationMode.CUSTOM:
            angle = float(config_dict.get("custom_angle", 0))
        else:
            angle = 0.0

        # Get fill color
        fill_color = tuple(config_dict.get("fill_color", [255, 255, 255]))

        config = RotationConfig(
            mode=mode,
            angle=angle,
            auto_detect_method=config_dict.get("auto_detect_method", "text_lines"),
            expand_canvas=config_dict.get("expand_canvas", False),
            fill_color=fill_color,
            output_format=config_dict.get("output_format", "png"),
            jpeg_quality=config_dict.get("jpeg_quality", 95),
        )

        # Extract image input from named inputs
        if "image" not in request.inputs:
            raise HTTPException(
                status_code=400,
                detail="Missing 'image' input in request",
            )

        image_input = request.inputs["image"]

        if image_input.binary and len(image_input.binary) > 1:
            rotated_binaries = []
            image_summaries = []
            mime = _MIME_MAP.get(config.output_format, f"image/{config.output_format}")

            for entry in image_input.binary:
                img_b64 = entry.get("data") or ""
                if not img_b64:
                    ref = entry.get("ref", "")
                    if ref and Path(ref).exists():
                        img_b64 = base64.b64encode(Path(ref).read_bytes()).decode("ascii")

                if not img_b64:
                    logger.warning("Skipping empty image entry in rotation multi-image input")
                    continue

                rotated, info = engine.rotate_from_base64(img_b64, config)
                rotated_b64 = engine.encode_to_base64(
                    rotated,
                    output_format=config.output_format,
                    jpeg_quality=config.jpeg_quality,
                )
                rotated_binaries.append(
                    {
                        "ref": "",
                        "data": rotated_b64,
                        "mime_type": mime,
                        "size_bytes": len(base64.b64decode(rotated_b64)),
                        "dimensions": _shape_to_dimensions(info["output_shape"]),
                    }
                )
                image_summaries.append(
                    {
                        "applied_angle": info["applied_angle"],
                        "mode": info["mode"],
                        "original_shape": list(info["original_shape"]),
                        "output_shape": list(info["output_shape"]),
                    }
                )

            if not rotated_binaries:
                raise HTTPException(
                    status_code=400,
                    detail="No valid image data found in inputs['image'].binary",
                )

            processing_time_ms = int((time.time() - start_time) * 1000)
            return {
                "text": None,
                "binary": rotated_binaries,
                "structured": None,
                "metadata": {
                    "processing_time_ms": processing_time_ms,
                    "image_count": len(rotated_binaries),
                    "images": image_summaries,
                },
            }

        base64_data = image_input.text

        if not base64_data and image_input.binary and len(image_input.binary) > 0:
            base64_data = image_input.binary[0].get("data") or ""

        if not base64_data and image_input.binary and len(image_input.binary) > 0:
            file_path = image_input.binary[0].get("ref")
            if file_path:
                rotated, info = engine.rotate_from_file(file_path, config)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No valid image data found in inputs['image']",
                )
        elif base64_data:
            rotated, info = engine.rotate_from_base64(base64_data, config)
        else:
            raise HTTPException(
                status_code=400,
                detail="No valid image data found in inputs['image']",
            )

        encode_params = []
        if config.output_format == "jpeg":
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality]
        success, buf = cv2.imencode(f".{config.output_format}", rotated, encode_params)
        if not success:
            raise RuntimeError("Failed to encode rotated image")
        image_bytes = buf.tobytes()
        rotated_b64 = base64.b64encode(image_bytes).decode("ascii")

        processing_time_ms = int((time.time() - start_time) * 1000)

        mime = _MIME_MAP.get(config.output_format, f"image/{config.output_format}")

        return {
            "text": None,
            "binary": [
                {
                    "ref": "",
                    "data": rotated_b64,
                    "mime_type": mime,
                    "size_bytes": len(image_bytes),
                }
            ],
            "structured": None,
            "metadata": {
                "processing_time_ms": processing_time_ms,
                "applied_angle": info["applied_angle"],
                "mode": info["mode"],
                "original_shape": info["original_shape"],
                "output_shape": info["output_shape"],
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Image rotation failed error_type=%s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "ROTATION_ERROR", "message": str(e)},
        ) from e


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Image Rotation Engine",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health - Basic health check",
            "config_schema": "GET /config - Get available rotation options",
            "process": "POST /process - Rotate image",
        },
    }


# For local development
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
