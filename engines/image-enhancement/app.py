"""
Image Enhancement Engine Service

API 規格：
- GET /health: 健康檢查
- GET /config: 获取可用的增强选项
- POST /process: 处理图片，返回增强后的图片

Output format (NodeOutput envelope):
{
    "text": null,
    "binary": [{"ref": "", "data": "<base64>", "mime_type": "image/png", "size_bytes": 12345}],
    "structured": null,
    "metadata": {
        "processing_time_ms": 1234,
        "enhancements_applied": ["clahe", "sharpen"],
        "original_shape": [1000, 800, 3],
        "output_shape": [1000, 800, 3]
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
from src.enhancement_engine import EnhancementConfig, ImageEnhancementEngine

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
    title="Image Enhancement Engine Service",
    description="Document image enhancement for better OCR/processing",
    version="1.0.0",
)

# Global engine instance
enhancement_engine: Optional[ImageEnhancementEngine] = None


def get_enhancement_engine() -> ImageEnhancementEngine:
    """Get or initialize enhancement engine."""
    global enhancement_engine
    if enhancement_engine is None:
        logger.info("Initializing Image Enhancement engine...")
        enhancement_engine = ImageEnhancementEngine()
        logger.info("Image Enhancement engine initialized successfully")
    return enhancement_engine


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
        engine="image-enhancement",
        version="1.0.0",
    )


@app.get("/config", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """Return available enhancement options"""
    return ConfigSchemaResponse(
        engine_type="image-enhancement",
        version="1.0.0",
        config_schema={
            "type": "object",
            "properties": {
                "clahe_enabled": {
                    "type": "boolean",
                    "default": True,
                    "title": "CLAHE Contrast Enhancement",
                    "description": "Apply Contrast Limited Adaptive Histogram Equalization",
                },
                "clahe_clip_limit": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 5.0,
                    "default": 2.0,
                    "title": "CLAHE Clip Limit",
                    "description": "Higher values = more contrast (may introduce noise)",
                },
                "denoise": {
                    "type": "boolean",
                    "default": False,
                    "title": "Denoise",
                    "description": "Remove noise from image (slower)",
                },
                "sharpen": {
                    "type": "boolean",
                    "default": False,
                    "title": "Sharpen",
                    "description": "Apply unsharp mask sharpening",
                },
            },
            "required": [],
        },
    )


@app.post("/process")
async def process(request: NewProcessRequest):
    """
    Enhance image quality.

    Accepts named-input format (inputs.image) and returns a NodeOutput envelope
    with the enhanced image saved as a temp file reference in binary.
    """
    start_time = time.time()

    try:
        engine = get_enhancement_engine()

        # Parse configuration
        config_dict = request.config or {}
        config = EnhancementConfig(
            clahe=config_dict.get("clahe", True),
            clahe_clip_limit=config_dict.get("clahe_clip_limit", 2.0),
            denoise=config_dict.get("denoise", False),
            denoise_strength=config_dict.get("denoise_strength", 10.0),
            sharpen=config_dict.get("sharpen", False),
            sharpen_strength=config_dict.get("sharpen_strength", 1.0),
            binarize=config_dict.get("binarize", False),
            binarize_method=config_dict.get("binarize_method", "otsu"),
            deskew=config_dict.get("deskew", False),
            auto_contrast=config_dict.get("auto_contrast", False),
            remove_shadow=config_dict.get("remove_shadow", False),
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
            enhanced_binaries = []
            image_summaries = []
            mime = _MIME_MAP.get(config.output_format, f"image/{config.output_format}")

            for entry in image_input.binary:
                img_b64 = entry.get("data") or ""
                if not img_b64:
                    ref = entry.get("ref", "")
                    if ref and Path(ref).exists():
                        img_b64 = base64.b64encode(Path(ref).read_bytes()).decode("ascii")

                if not img_b64:
                    logger.warning("Skipping empty image entry in enhancement multi-image input")
                    continue

                enhanced, info = engine.enhance_from_base64(img_b64, config)
                enhanced_b64 = engine.encode_to_base64(
                    enhanced,
                    output_format=config.output_format,
                    jpeg_quality=config.jpeg_quality,
                )
                enhanced_binaries.append(
                    {
                        "ref": "",
                        "data": enhanced_b64,
                        "mime_type": mime,
                        "size_bytes": len(base64.b64decode(enhanced_b64)),
                        "dimensions": _shape_to_dimensions(info["output_shape"]),
                    }
                )
                image_summaries.append(
                    {
                        "enhancements_applied": info["applied_enhancements"],
                        "original_shape": list(info["original_shape"]),
                        "output_shape": list(info["output_shape"]),
                    }
                )

            if not enhanced_binaries:
                raise HTTPException(
                    status_code=400,
                    detail="No valid image data found in inputs['image'].binary",
                )

            processing_time_ms = int((time.time() - start_time) * 1000)
            return {
                "text": None,
                "binary": enhanced_binaries,
                "structured": None,
                "metadata": {
                    "processing_time_ms": processing_time_ms,
                    "image_count": len(enhanced_binaries),
                    "images": image_summaries,
                },
            }

        base64_data = image_input.text

        if not base64_data and image_input.binary and len(image_input.binary) > 0:
            base64_data = image_input.binary[0].get("data") or ""

        if not base64_data and image_input.binary and len(image_input.binary) > 0:
            file_path = image_input.binary[0].get("ref")
            if file_path:
                enhanced, info = engine.enhance_from_file(file_path, config)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No valid image data found in inputs['image']",
                )
        elif base64_data:
            enhanced, info = engine.enhance_from_base64(base64_data, config)
        else:
            raise HTTPException(
                status_code=400,
                detail="No valid image data found in inputs['image']",
            )

        encode_params = []
        if config.output_format == "jpeg":
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality]
        success, buf = cv2.imencode(f".{config.output_format}", enhanced, encode_params)
        if not success:
            raise RuntimeError("Failed to encode enhanced image")
        image_bytes = buf.tobytes()
        enhanced_b64 = base64.b64encode(image_bytes).decode("ascii")

        processing_time_ms = int((time.time() - start_time) * 1000)

        mime = _MIME_MAP.get(config.output_format, f"image/{config.output_format}")

        return {
            "text": None,
            "binary": [
                {
                    "ref": "",
                    "data": enhanced_b64,
                    "mime_type": mime,
                    "size_bytes": len(image_bytes),
                }
            ],
            "structured": None,
            "metadata": {
                "processing_time_ms": processing_time_ms,
                "enhancements_applied": info["applied_enhancements"],
                "original_shape": list(info["original_shape"]),
                "output_shape": list(info["output_shape"]),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Image enhancement failed error_type=%s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "ENHANCEMENT_ERROR", "message": str(e)},
        ) from e


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Image Enhancement Engine",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health - Basic health check",
            "config_schema": "GET /config - Get available enhancement options",
            "process": "POST /process - Enhance image",
        },
    }


# For local development
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
