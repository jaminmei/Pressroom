"""
OCR Engine Service - PaddleOCR v5

統一 API 規格：
- POST /process: 處理圖片輸入，輸出 NodeOutput 格式
- GET /health: 健康檢查
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from src.ocr_engine import OCREngine, OCREngineManager

# OCR engine type - using RapidOCR (ONNX-based) for better CPU compatibility
OCR_ENGINE_TYPE = "rapidocr"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OCR Engine Service",
    description="PaddleOCR v5 engine for document text extraction",
    version="1.0.0",
)

# Initialize OCR engine (lazy loading, per-language caching)
ocr_engine_manager: Optional[OCREngineManager] = None


def get_ocr_engine_manager() -> OCREngineManager:
    """Get or initialize OCR engine manager."""
    global ocr_engine_manager
    if ocr_engine_manager is None:
        logger.info("Initializing OCR engine manager...")
        try:
            ocr_engine_manager = OCREngineManager()
            logger.info("OCR engine manager initialized successfully")
        except Exception as err:
            logger.error(
                "OCR engine manager initialization failed error_type=%s",
                type(err).__name__,
            )
            raise RuntimeError(
                f"OCR engine initialization failed: {str(err)}. "
                "This may be due to CPU incompatibility (AVX instructions required) "
                "or missing dependencies."
            ) from err
    return ocr_engine_manager


# === Request/Response Models ===


class NodeOutputInput(BaseModel):
    """Input data matching NodeOutput schema"""

    text: Optional[str] = None
    binary: list[dict] = []
    structured: Optional[dict] = None
    metadata: dict = {}


class NewProcessRequest(BaseModel):
    """Named-input processing request"""

    inputs: dict[str, NodeOutputInput]
    config: dict = {}


class HealthResponse(BaseModel):
    """健康檢查回應"""

    status: str
    model: str
    version: str
    gpu_available: bool


class ConfigResponse(BaseModel):
    """Configuration schema response"""

    engine_type: str
    version: str
    config_schema: dict


# === API Endpoints ===


async def _process_single_image(img_b64: str, config: dict, engine: OCREngine) -> list:
    return await asyncio.to_thread(engine.process_base64, img_b64, config)


@app.post("/process")
async def process(request: NewProcessRequest):
    """
    Named-input processing endpoint

    Input:
        - inputs: dict of port_name -> NodeOutputInput
          - Look for key "images" or "image" with base64 data in .text
            or file_path in .binary[0].ref
        - config: optional engine configuration

    Output:
        - NodeOutput: {"text": ..., "binary": [], "structured": null, "metadata": {...}}
    """
    start_time = time.time()

    try:
        manager = get_ocr_engine_manager()

        # Extract config parameters
        config = request.config or {}
        lang = config.get("language", "ch")
        use_angle_cls = config.get("use_angle_cls", True)
        engine = manager.get_engine(lang=lang, use_angle_cls=use_angle_cls)

        # Find image input port
        image_input = None
        base64_data = None
        file_path = None

        for key in ("images", "image"):
            if key in request.inputs:
                image_input = request.inputs[key]
                break

        if image_input is None:
            raise HTTPException(
                status_code=400,
                detail="No image input found. Provide 'images' or 'image' in inputs.",
            )

        # Multi-image path: binary has multiple entries with data
        if image_input.binary and len(image_input.binary) > 1:
            all_text_lines = []
            all_blocks = []
            block_offset = 0
            image_count = 0

            for b in image_input.binary:
                img_b64 = b.get("data") or ""
                if not img_b64:
                    ref = b.get("ref", "")
                    if ref and Path(ref).exists():
                        import base64 as _b64mod

                        img_b64 = _b64mod.b64encode(Path(ref).read_bytes()).decode("ascii")
                if not img_b64:
                    logger.warning("Skipping empty image entry in multi-image input")
                    continue

                image_count += 1
                logger.info(f"Processing multi-image entry {image_count}")
                per_result = await _process_single_image(img_b64, config, engine)

                for block in per_result:
                    if isinstance(block, (list, tuple)) and len(block) >= 2:
                        bbox = block[0]
                        text_content = (
                            block[1][0] if isinstance(block[1], (list, tuple)) else str(block[1])
                        )
                        confidence = (
                            block[1][1]
                            if isinstance(block[1], (list, tuple)) and len(block[1]) > 1
                            else None
                        )
                        all_text_lines.append(text_content)
                        all_blocks.append(
                            {
                                "index": block_offset,
                                "text": text_content,
                                "confidence": float(confidence) if confidence is not None else None,
                                "bbox": bbox if isinstance(bbox, list) else None,
                            }
                        )
                        block_offset += 1
                    elif isinstance(block, dict) and "text" in block:
                        all_text_lines.append(block["text"])
                        all_blocks.append({**block, "index": block_offset})
                        block_offset += 1
                    elif isinstance(block, str):
                        all_text_lines.append(block)
                        all_blocks.append({"index": block_offset, "text": block})
                        block_offset += 1

            output_text = "\n".join(all_text_lines)
            block_count = len(all_blocks)
            processing_time = int((time.time() - start_time) * 1000)
            logger.info(
                f"Multi-image OCR: {image_count} images, {block_count} blocks, {processing_time}ms"
            )

            return {
                "text": output_text,
                "binary": [],
                "structured": {
                    "result": output_text,
                    "blocks": all_blocks,
                    "block_count": block_count,
                },
                "metadata": {
                    "processing_time_ms": processing_time,
                    "block_count": block_count,
                    "image_count": image_count,
                },
            }

        # Single-image path (backward compatible)
        if image_input.text:
            base64_data = image_input.text
        elif image_input.binary and len(image_input.binary) > 0:
            data = image_input.binary[0].get("data")
            if data:
                base64_data = data
            else:
                file_path = image_input.binary[0].get("ref")

        # Process based on extracted input
        if base64_data:
            logger.info("Processing image from base64 data (named input)")
            ocr_result = await _process_single_image(base64_data, config, engine)
        elif file_path:
            if not Path(file_path).exists():
                raise HTTPException(status_code=400, detail=f"File not found: {file_path}")
            logger.info("Processing image from file reference")
            ocr_result = await asyncio.to_thread(engine.process_image, file_path, config)
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No image data found in input. Provide base64 in .text "
                    "or file_path in .binary[0].ref"
                ),
            )

        # Build text output and structured blocks
        text_lines = []
        structured_blocks = []
        for idx, block in enumerate(ocr_result):
            if isinstance(block, (list, tuple)) and len(block) >= 2:
                bbox = block[0]
                text_content = block[1][0] if isinstance(block[1], (list, tuple)) else str(block[1])
                confidence = (
                    block[1][1]
                    if isinstance(block[1], (list, tuple)) and len(block[1]) > 1
                    else None
                )
                text_lines.append(text_content)
                structured_blocks.append(
                    {
                        "index": idx,
                        "text": text_content,
                        "confidence": float(confidence) if confidence is not None else None,
                        "bbox": bbox if isinstance(bbox, list) else None,
                    }
                )
            elif isinstance(block, dict) and "text" in block:
                text_lines.append(block["text"])
                structured_blocks.append(block)
            elif isinstance(block, str):
                text_lines.append(block)
                structured_blocks.append({"index": idx, "text": block})
            else:
                text_lines.append(str(block))
                structured_blocks.append({"index": idx, "text": str(block)})

        output_text = "\n".join(text_lines)
        block_count = len(ocr_result)
        processing_time = int((time.time() - start_time) * 1000)

        logger.info(f"OCR processing completed: {block_count} text blocks, {processing_time}ms")

        return {
            "text": output_text,
            "binary": [],
            "structured": {
                "result": output_text,
                "blocks": structured_blocks,
                "block_count": block_count,
            },
            "metadata": {
                "processing_time_ms": processing_time,
                "block_count": block_count,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OCR processing failed error_type=%s", type(e).__name__)
        raise HTTPException(
            status_code=500, detail={"code": "PROCESSING_FAILED", "message": str(e)}
        ) from e


@app.get("/health", response_model=HealthResponse)
async def health():
    """
    健康檢查端點

    Note: This endpoint returns basic health status without initializing the OCR model.
    The model will be loaded lazily on first /process request.
    """
    try:
        # Basic health check - service is running
        # We don't initialize the model here to avoid slow health checks

        return HealthResponse(
            status="healthy",
            model="rapidocr-onnx",
            version="1.3.24",
            gpu_available=False,  # ONNX CPU version doesn't support GPU
        )
    except Exception as e:
        logger.error("OCR health check failed error_type=%s", type(e).__name__)
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@app.get("/health/full")
async def health_full():
    """
    完整健康檢查端點（包含模型初始化）

    Warning: This endpoint will initialize the OCR model if not already loaded.
    This may take time on first call.
    """
    try:
        manager = get_ocr_engine_manager()
        # Get default Chinese engine for health check
        engine = manager.get_engine(lang="ch")

        return {
            "status": "healthy",
            "model": "rapidocr-onnx",
            "version": "1.3.24",
            "gpu_available": engine.is_gpu_available(),
            "model_info": engine.get_model_info(),
        }
    except Exception as e:
        logger.error("OCR full health check failed error_type=%s", type(e).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "hint": "OCR model initialization failed. Check logs for details.",
            },
        )


@app.get("/config", response_model=ConfigResponse)
async def get_config():
    """Return engine configuration schema"""
    return ConfigResponse(
        engine_type="ocr",
        version="1.0.0",
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
    )


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "OCR Engine",
        "model": "RapidOCR (ONNX Runtime)",
        "version": "1.0.0",
        "endpoints": {
            "process": "POST /process - Process image and return NodeOutput",
            "health": "GET /health - Basic health check",
            "health_full": "GET /health/full - Full health check with model initialization",
            "config": "GET /config - Get engine configuration schema",
        },
    }


# For local development
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
