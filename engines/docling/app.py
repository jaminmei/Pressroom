# engines/docling/app.py
"""
Docling Engine Service

Converts various document formats to NodeOutput format via Docling.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.docling_engine import DoclingEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Docling Engine Service",
    description="Multi-format document conversion engine using IBM Docling",
    version="1.0.0",
)

# Initialize engines (lazy loading)
docling_engine: Optional[DoclingEngine] = None


def get_docling_engine() -> DoclingEngine:
    """Get or initialize Docling engine"""
    global docling_engine
    if docling_engine is None:
        logger.info("Initializing Docling engine...")
        try:
            docling_engine = DoclingEngine()
            logger.info("Docling engine initialized successfully")
        except Exception as e:
            logger.error("Docling engine initialization failed error_type=%s", type(e).__name__)
            raise RuntimeError(f"Docling engine initialization failed: {str(e)}") from e
    return docling_engine


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
    supported_formats: list


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
          - Look for key "document" or "file"
          - Binary data: .binary[0].ref (file path on shared volume)
          - Text data: .text (raw text content, written to temp file)
        - config: optional engine configuration

    Output:
        - NodeOutput: {"text": ..., "binary": [], "structured": null, "metadata": {...}}
    """
    start_time = time.time()
    temp_file_path: str | None = None

    try:
        engine = get_docling_engine()
        config = request.config or {}

        # Find document input port
        doc_input = None
        for key in ("document", "file"):
            if key in request.inputs:
                doc_input = request.inputs[key]
                break

        if doc_input is None:
            raise HTTPException(
                status_code=400,
                detail="No document input found. Provide 'document' or 'file' in inputs.",
            )

        # Determine file path to process
        file_path_to_process: str | None = None

        if doc_input.binary:
            # Binary ref — file path on shared volume
            ref = doc_input.binary[0].get("ref", "")
            if ref and Path(ref).exists():
                file_path_to_process = ref
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Binary ref path is missing or file does not exist.",
                )
        elif doc_input.text:
            # Raw text content — write to temp file for Docling to process
            file_extension = doc_input.metadata.get("file_extension") or config.get(
                "file_extension_hint", ".txt"
            )
            if not file_extension.startswith("."):
                file_extension = "." + file_extension

            import tempfile

            tmp = tempfile.NamedTemporaryFile(
                suffix=file_extension,
                delete=False,
                mode="w",
                encoding="utf-8",
            )
            tmp.write(doc_input.text)
            tmp.close()
            file_path_to_process = tmp.name
            temp_file_path = tmp.name
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No document data found. Provide file path in .binary[0].ref "
                    "or text content in .text."
                ),
            )

        if not file_path_to_process or not Path(file_path_to_process).exists():
            raise HTTPException(status_code=400, detail="File not found.")

        logger.info("Processing document from file reference")
        markdown_text = engine.process_file(file_path_to_process, config=config)

        processing_time = int((time.time() - start_time) * 1000)

        logger.info(
            f"Docling processing completed: {len(markdown_text)} chars, {processing_time}ms"
        )

        return {
            "text": markdown_text,
            "binary": [],
            "structured": None,
            "metadata": {
                "processing_time_ms": processing_time,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Docling processing failed error_type=%s", type(e).__name__)
        raise HTTPException(
            status_code=500, detail={"code": "PROCESSING_FAILED", "message": str(e)}
        ) from e
    finally:
        if temp_file_path:
            Path(temp_file_path).unlink(missing_ok=True)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint (lightweight — no engine init)"""
    return HealthResponse(
        status="healthy",
        model="IBM Docling",
        version="1.0.0",
        gpu_available=False,
        supported_formats=[
            ".pdf",
            ".docx",
            ".pptx",
            ".html",
            ".htm",
            ".txt",
            ".md",
            ".png",
            ".jpg",
            ".jpeg",
            ".tiff",
        ],
    )


@app.get("/health/full")
async def health_full():
    """Full health check endpoint"""
    try:
        engine = get_docling_engine()
        return {
            "status": "healthy",
            "model": "IBM Docling",
            "version": "1.0.0",
            "gpu_available": False,
            "supported_formats": engine.get_supported_extensions(),
            "model_info": engine.get_model_info(),
        }
    except Exception as e:
        logger.error("Docling full health check failed error_type=%s", type(e).__name__)
        return {"status": "unhealthy", "error": str(e)}


@app.get("/config", response_model=ConfigResponse)
async def get_config():
    """Return engine configuration schema"""
    return ConfigResponse(
        engine_type="docling",
        version="1.0.0",
        config_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Docling Engine",
        "model": "IBM Docling",
        "version": "1.0.0",
        "endpoints": {
            "process": "POST /process - Convert document and return NodeOutput",
            "health": "GET /health - Basic health check",
            "health_full": "GET /health/full - Full health check",
            "config": "GET /config - Get engine configuration schema",
        },
    }
