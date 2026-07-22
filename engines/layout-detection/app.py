"""
Layout Detection Engine Service

API 規格：
- GET /health: 健康檢查
- GET /config: 获取配置选项 schema
- GET /models: 获取可用模型列表
- GET /layout-types: 获取当前配置支持的布局类型
- POST /process: 处理图片，返回布局检测结果 (NodeOutput format)

POST /process accepts a named-input request:
{
    "inputs": {
        "image": {"text": "base64_data", "binary": [], "structured": null, "metadata": {}}
    },
    "config": {"selected_types": ["Text", "Table"]}
}

Returns a NodeOutput envelope:
{
    "text": null,
    "binary": [...],
    "structured": {"elements": [...], "total_regions": N},
    "metadata": {"processing_time_ms": N, "model": "..."}
}
"""

import base64
import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from src.layout_engine import LayoutEngine
from src.model_manager import ModelConfig, get_model_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Layout Detection Engine Service",
    description="Document layout analysis with multiple model support",
    version="1.0.0",
)

# Global instances
layout_engine: Optional[LayoutEngine] = None
current_config: Optional[ModelConfig] = None
_engine_lock = threading.Lock()


def get_layout_engine(config: Optional[ModelConfig] = None) -> LayoutEngine:
    """Get or initialize layout engine with given config (thread-safe)."""
    global layout_engine, current_config

    target_config = config or get_model_manager().get_model_config()

    # Fast path: engine already initialized with matching config
    if layout_engine is not None and current_config == target_config:
        return layout_engine

    # Slow path: acquire lock for initialization
    with _engine_lock:
        # Double-check after acquiring lock
        if layout_engine is not None and current_config == target_config:
            return layout_engine
        logger.info("Initializing layout engine")
        layout_engine = LayoutEngine(model_config=target_config)
        current_config = target_config

    return layout_engine


# === Request/Response Models ===


class NodeOutputInput(BaseModel):
    """Single input slot in the named-input request format."""

    text: Optional[str] = None
    binary: list[dict] = []
    structured: Optional[dict] = None
    metadata: dict = {}


class NewProcessRequest(BaseModel):
    """Named-input request format sent by the backend EngineClient."""

    inputs: dict[str, NodeOutputInput]
    config: dict = {}


class HealthResponse(BaseModel):
    """健康檢查回應"""

    status: str
    engine: str
    version: str
    model: Optional[str] = None


class ConfigSchemaResponse(BaseModel):
    """Configuration schema response"""

    engine_type: str
    version: str
    config_schema: dict


class ModelInfo(BaseModel):
    """模型信息"""

    id: str
    display_name: str
    description: Optional[str] = None
    supported_languages: list[str] = []
    model_files: list[dict]


class ModelsResponse(BaseModel):
    """可用模型列表"""

    models: list[ModelInfo]
    default_model: str
    default_model_file: str
    default_language: str


class LayoutTypesResponse(BaseModel):
    """支持的布局类型"""

    model: str
    model_file: str
    language: str
    layout_types: list[str]


# === API Endpoints ===


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        engine="layout-detection",
        version="1.0.0",
        model=current_config.model_id if current_config else None,
    )


@app.get("/config", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """Return available layout detection configuration options.

    IMPORTANT: The ``config_schema`` returned here must stay in sync with
    the ``processor/layout_detection`` node definition in
    ``app/services/node_registry.py``. Changes to field names, types, or
    enum values require updating both files.
    """
    return ConfigSchemaResponse(
        engine_type="layout-detection",
        version="1.0.0",
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
                            "Figure_caption": {"display_name": "Figure Caption (图片说明)"},
                            "Table_caption": {"display_name": "Table Caption (表格说明)"},
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
            "required": [],
        },
    )


@app.get("/health/full")
async def health_full():
    """Full health check with model initialization"""
    try:
        engine = get_layout_engine()
        return {
            "status": "healthy",
            "engine": "layout-detection",
            "version": "1.0.0",
            "model": engine.model_config.model_id,
            "model_file": engine.model_config.model_file,
            "supported_types": engine.get_supported_types(),
        }
    except Exception as e:
        logger.error("Layout full health check failed error_type=%s", type(e).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
            },
        )


@app.get("/models", response_model=ModelsResponse)
async def get_models():
    """获取可用的模型列表"""
    manager = get_model_manager()
    models = manager.get_available_models()

    return ModelsResponse(
        models=[ModelInfo(**m) for m in models],
        default_model=manager.mapping_data.get("default_model", "ppstructure_v2"),
        default_model_file=manager.mapping_data.get("default_model_file", "picodet_lcnet_x1_0"),
        default_language=manager.mapping_data.get("default_language", "ch"),
    )


@app.get("/layout-types", response_model=LayoutTypesResponse)
async def get_layout_types(
    model: Optional[str] = None,
    model_file: Optional[str] = None,
    language: Optional[str] = None,
):
    """获取指定配置支持的布局类型"""
    manager = get_model_manager()
    config = manager.get_model_config(model, model_file, language)

    return LayoutTypesResponse(
        model=config.model_id,
        model_file=config.model_file,
        language=config.language,
        layout_types=config.layout_types,
    )


def _crop_regions_to_base64(
    image_data_b64: str,
    regions: list[dict],
) -> list[dict]:
    """Crop all regions from the source image and return base64-encoded crops."""
    try:
        img_bytes = base64.b64decode(image_data_b64)
    except Exception as exc:
        logger.warning(
            "Failed to decode base64 for region cropping; skipping crops error_type=%s",
            type(exc).__name__,
        )
        return []
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        logger.warning("Failed to decode image for region cropping; skipping crops")
        return []

    binary_output: list[dict] = []
    for _i, region in enumerate(regions):
        bbox = region.get("bbox", {})
        x, y = int(bbox.get("x", 0)), int(bbox.get("y", 0))
        w, h = int(bbox.get("width", 0)), int(bbox.get("height", 0))
        if w <= 0 or h <= 0:
            continue
        x = max(0, x)
        y = max(0, y)
        h = min(h, img.shape[0] - y)
        w = min(w, img.shape[1] - x)
        if w <= 0 or h <= 0:
            continue
        crop = img[y : y + h, x : x + w]
        _, crop_encoded = cv2.imencode(".png", crop)
        crop_b64 = base64.b64encode(crop_encoded).decode("ascii")
        binary_output.append(
            {
                "ref": "",
                "data": crop_b64,
                "mime_type": "image/png",
                "dimensions": bbox,
            }
        )
    return binary_output


async def _detect_regions(base64_data, file_path, selected_types, config, engine):
    if base64_data:
        return engine.detect_from_base64(base64_data, selected_types), None
    return engine.detect_from_file(file_path, selected_types), None


@app.post("/process")
async def process_image(request: NewProcessRequest):  # type: ignore[assignment]
    """
    Process an image for layout detection using the named-input request format.

    Expects ``inputs["image"]`` with base64 data in the ``text`` field (or a
    file path in ``binary[0].ref``).  Returns a **NodeOutput** envelope with
    cropped region images in ``binary`` and region metadata in ``structured``.

    Config options (inside ``config``):
    - model: Model identifier
    - language: Language code (e.g. "en", "ch")
    - selected_types: Filter results to only these layout types
    """
    start_time = time.time()

    try:
        # --- Extract image input ------------------------------------------------
        image_input = request.inputs.get("image")
        if image_input is None:
            raise HTTPException(
                status_code=400,
                detail='Missing "image" key in inputs',
            )

        base64_data: Optional[str] = None
        file_path: Optional[str] = None

        if image_input.text:
            base64_data = image_input.text
        elif image_input.binary and len(image_input.binary) > 0:
            base64_data = image_input.binary[0].get("data") or ""
            if not base64_data:
                file_path = image_input.binary[0].get("ref")
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Must provide image via inputs.image.text (base64) or "
                    "inputs.image.binary[0].ref (file path)"
                ),
            )

        # --- Configuration ------------------------------------------------------
        config = request.config or {}
        model = config.get("model")
        language = config.get("language")
        selected_types = config.get("selected_types")

        manager = get_model_manager()
        model_config = manager.get_model_config(model, None, language)
        engine = get_layout_engine(model_config)

        # --- Run detection ------------------------------------------------------
        regions, provider_metadata = await _detect_regions(
            base64_data, file_path, selected_types, config, engine
        )

        # --- Post-processing: crop ALL regions as base64 -----------------------
        binary_output: list[dict] = []
        crop_b64 = base64_data
        if not crop_b64 and file_path:
            import pathlib as _pl

            crop_b64 = base64.b64encode(_pl.Path(file_path).read_bytes()).decode("ascii")
        if crop_b64:
            binary_output = _crop_regions_to_base64(crop_b64, regions)

        processing_time_ms = int((time.time() - start_time) * 1000)

        # --- Build NodeOutput response ------------------------------------------
        page_dimensions = None
        if crop_b64:
            try:
                _img_bytes = base64.b64decode(crop_b64)
                _nparr = np.frombuffer(_img_bytes, np.uint8)
                _img = cv2.imdecode(_nparr, cv2.IMREAD_COLOR)
                if _img is not None:
                    page_dimensions = {"width": _img.shape[1], "height": _img.shape[0]}
            except Exception:
                pass

        structured: dict = {
            "kind": "layout_regions",
            "elements": regions,
            "total_regions": len(regions),
        }
        if page_dimensions:
            structured["page_dimensions"] = page_dimensions

        metadata = {
            "processing_time_ms": processing_time_ms,
            "model": model_config.model_id,
            "model_file": model_config.model_file,
            "language": model_config.language,
        }
        if provider_metadata:
            metadata.update(provider_metadata)

        return {
            "text": None,
            "binary": binary_output,
            "structured": structured,
            "metadata": metadata,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Layout processing failed error_type=%s", type(e).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "text": None,
                "binary": [],
                "structured": None,
                "metadata": {
                    "error": {
                        "code": "PROCESSING_ERROR",
                        "message": str(e),
                    },
                },
            },
        )


@app.post("/detect")
async def detect_layout(request: NewProcessRequest):
    """Alias for /process endpoint"""
    return await process_image(request)


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Layout Detection Engine",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health - Basic health check",
            "health_full": "GET /health/full - Full health check with model init",
            "models": "GET /models - Get available models",
            "layout_types": "GET /layout-types - Get supported layout types",
            "process": "POST /process - Process image and return layout regions",
        },
    }


# For local development
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
