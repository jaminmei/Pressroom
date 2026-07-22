# SPDX-License-Identifier: GPL-3.0-only
# engines/text/app.py
"""
Text Engine Service

Processes plain text and HTML content, outputs NodeOutput format.
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.text_engine import TextEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Text Engine Service",
    description="Text/HTML processing engine for document conversion",
    version="1.0.0",
)

# Initialize engines (lazy loading)
text_engine: Optional[TextEngine] = None


def get_text_engine() -> TextEngine:
    """Get or initialize Text engine"""
    global text_engine
    if text_engine is None:
        logger.info("Initializing Text engine...")
        text_engine = TextEngine()
        logger.info("Text engine initialized successfully")
    return text_engine


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
    """Health check response"""

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


@app.post("/process")
async def process(request: NewProcessRequest):
    """
    Named-input processing endpoint

    Input:
        - inputs: dict of port_name -> NodeOutputInput
          - Look for key "text" or "content" with text data in .text
        - config: optional engine configuration

    Output:
        - NodeOutput: {"text": ..., "binary": [], "structured": null, "metadata": {...}}
    """
    start_time = time.time()

    try:
        engine = get_text_engine()

        config = request.config or {}
        content_format = config.get("format_hint", "text")

        # Find text input port
        text_input = None
        for key in ("text", "content"):
            if key in request.inputs:
                text_input = request.inputs[key]
                break

        if text_input is None or not text_input.text:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No text input found. Provide 'text' or 'content' in inputs with .text field."
                ),
            )

        raw_text = text_input.text

        # Process content
        if content_format == "html":
            logger.info("Processing direct text as HTML")
            result = await asyncio.to_thread(engine.process_html, raw_text, config)
        else:
            logger.info("Processing direct text")
            result = await asyncio.to_thread(engine.process_text, raw_text, config)

        # Concatenate block text content directly (no DocTags conversion)
        text_lines = []
        for block in result:
            if isinstance(block, dict) and "text" in block:
                text_lines.append(block["text"])
            elif isinstance(block, str):
                text_lines.append(block)
            else:
                text_lines.append(str(block))

        output_text = "\n".join(text_lines)
        processing_time = int((time.time() - start_time) * 1000)

        logger.info(f"Text processing completed: {len(result)} blocks, {processing_time}ms")

        return {
            "text": output_text,
            "binary": [],
            "structured": None,
            "metadata": {
                "processing_time_ms": processing_time,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Text processing failed error_type=%s", type(e).__name__)
        raise HTTPException(
            status_code=500, detail={"code": "PROCESSING_FAILED", "message": str(e)}
        ) from e


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy", model="rule-based", version="1.0.0", gpu_available=False
    )


@app.get("/health/full")
async def health_full():
    """Full health check endpoint"""
    try:
        engine = get_text_engine()
        return {
            "status": "healthy",
            "model": "rule-based",
            "version": "1.0.0",
            "gpu_available": False,
            "model_info": engine.get_model_info(),
        }
    except Exception as e:
        logger.error("Text full health check failed error_type=%s", type(e).__name__)
        return {"status": "unhealthy", "error": str(e)}


@app.get("/config", response_model=ConfigResponse)
async def get_config():
    """Return engine configuration schema"""
    return ConfigResponse(
        engine_type="text",
        version="1.0.0",
        config_schema={
            "type": "object",
            "properties": {
                "encoding": {
                    "type": "string",
                    "enum": ["auto", "utf-8", "utf-8-sig", "big5", "gb2312", "gbk", "shift_jis"],
                    "default": "auto",
                    "title": "Character Encoding",
                    "description": "Text encoding for parsing. 'auto' will attempt detection.",
                },
                "format_hint": {
                    "type": "string",
                    "enum": ["auto", "plain", "html", "xml", "csv", "json"],
                    "default": "auto",
                    "title": "Format Hint",
                    "description": "Input format hint for better parsing",
                },
            },
            "required": [],
        },
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Text Engine",
        "model": "Rule-based text processor",
        "version": "1.0.0",
        "supported_formats": ["text", "html"],
        "endpoints": {
            "process": "POST /process - Process text/HTML and return NodeOutput",
            "health": "GET /health - Basic health check",
            "health_full": "GET /health/full - Full health check",
            "config": "GET /config - Get engine configuration schema",
        },
    }
