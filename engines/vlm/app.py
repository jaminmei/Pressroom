# engines/vlm/app.py
"""
VLM Engine Service - OpenAI-compatible provider adapters

Unified API specification:
- POST /process: Process image input, output DocTags format
- GET /health: Health check
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from src.vlm_engine import CredentialKind, VLMEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VLM Engine Service",
    description="Vision Language Model engine for OpenAI-compatible providers",
    version="1.0.0",
)

# Initialize VLM engine (lazy loading)
vlm_engine: Optional[VLMEngine] = None

# Read deployment name from env for consistent health reporting
_VLM_DEPLOYMENT_NAME = os.getenv("VLM_DEPLOYMENT_NAME", "gpt-4.1")
_CREDENTIAL_KIND_HEADER = "x-docconv-credential-kind"
_CREDENTIAL_HEADER = "x-docconv-credential"
_INTERNAL_METADATA_KEY = "_vlm_metadata"


def get_vlm_engine() -> VLMEngine:
    """Get or initialize VLM engine"""
    global vlm_engine
    if vlm_engine is None:
        logger.info("Initializing VLM engine")
        try:
            vlm_engine = VLMEngine(
                deployment_name=os.getenv("VLM_DEPLOYMENT_NAME", "gpt-4.1"),
            )
            logger.info("VLM engine initialized successfully")
        except Exception as exc:
            logger.error("VLM engine initialization failed error_type=%s", type(exc).__name__)
            raise RuntimeError("VLM engine initialization failed") from exc
    return vlm_engine


# === Request/Response Models ===


class NodeOutputInput(BaseModel):
    """Input data matching NodeOutput schema from DAG scheduler"""

    text: Optional[str] = None
    binary: list[dict] = []
    structured: Optional[dict] = None
    metadata: dict = {}


class NewProcessRequest(BaseModel):
    """Named-input processing request (DAG scheduler format)"""

    inputs: dict[str, NodeOutputInput]
    config: dict = {}


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    version: str


class ConfigResponse(BaseModel):
    """Configuration schema response"""

    engine_type: str
    version: str
    config_schema: dict


# VLM Configuration Schema (matches node_registry.py)
VLM_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {
            "type": "string",
            "title": "Model",
            "description": "VLM model to use for document understanding",
            "enum": [
                "gpt-4o-240806",
                "gpt-4.1",
                "gpt-4.1-mini",
                "gpt-4.1-nano",
                "gpt-5",
                "gpt-5.1",
                "gpt-5.2",
                "gpt-5-mini",
                "gpt-5-nano",
            ],
            "enum_metadata": {
                "gpt-4o-240806": {"group": "gpt_regular", "display_name": "GPT-4o"},
                "gpt-4.1": {"group": "gpt_regular", "display_name": "GPT-4.1"},
                "gpt-4.1-mini": {"group": "gpt_regular", "display_name": "GPT-4.1 Mini"},
                "gpt-4.1-nano": {"group": "gpt_regular", "display_name": "GPT-4.1 Nano"},
                "gpt-5": {"group": "gpt_inference", "display_name": "GPT-5"},
                "gpt-5.1": {"group": "gpt_inference", "display_name": "GPT-5.1"},
                "gpt-5.2": {"group": "gpt_inference", "display_name": "GPT-5.2"},
                "gpt-5-mini": {"group": "gpt_inference", "display_name": "GPT-5 Mini"},
                "gpt-5-nano": {"group": "gpt_inference", "display_name": "GPT-5 Nano"},
            },
            "default": "gpt-4.1",
        },
        "prompt": {
            "type": "string",
            "title": "Custom Prompt",
            "description": "Instruction for the VLM model. Default extracts structured content.",
            "default": (
                "Analyze this document and extract all content.\n\n"
                'Output JSON with a "result" key containing the full extracted text, '
                'and a "structured" key with block-level detail:\n'
                '{"result": "full extracted text", "structured": {"blocks": '
                '[{"type": "title"|"paragraph"|"list"|"table"|"figure", '
                '"text": "...", "level": 1-6 (titles only), "confidence": 0.0-1.0}]}}\n\n'
                "Rules:\n"
                '1. type="title" for titles with level (1=main, 2=subtitle)\n'
                '2. type="paragraph" for paragraphs\n'
                '3. type="list" for lists\n'
                '4. type="table" for tables (Markdown format)\n'
                '5. type="figure" for images/diagrams (describe content)\n'
                "6. Each block needs a confidence value (0-1)\n"
                "Output only JSON."
            ),
        },
        "temperature": {
            "type": "number",
            "minimum": 0,
            "maximum": 2,
            "default": 0,
            "title": "Temperature",
            "description": "Sampling temperature (not available for GPT-5.x inference models)",
            "applicable_groups": ["gpt_regular"],
        },
        "max_tokens": {
            "type": "integer",
            "minimum": 100,
            "maximum": 16000,
            "default": 4096,
            "title": "Max Tokens",
            "description": "Maximum tokens to generate (for GPT-4.x models)",
            "applicable_groups": ["gpt_regular"],
        },
        "max_completion_tokens": {
            "type": "integer",
            "minimum": 100,
            "maximum": 32000,
            "default": 4096,
            "title": "Max Completion Tokens",
            "description": "Maximum completion tokens (for GPT-5.x inference models)",
            "applicable_groups": ["gpt_inference"],
        },
        "reasoning_effort": {
            "type": "string",
            "enum": ["MINIMAL", "LOW", "MEDIUM", "HIGH"],
            "default": "MINIMAL",
            "title": "Reasoning Effort",
            "description": "Reasoning intensity for GPT-5.x models",
            "applicable_groups": ["gpt_inference"],
        },
    },
    "model_groups": {
        "gpt_regular": {
            "display_name": "GPT Regular (4.x)",
            "description": "Standard GPT models with configurable temperature",
        },
        "gpt_inference": {
            "display_name": "GPT Inference (5.x)",
            "description": "Reasoning models with fixed temperature=1",
        },
    },
    "required": [],
}


# === API Endpoints ===


@app.post("/process")
async def process(request: NewProcessRequest, raw_request: Request) -> dict[str, Any]:
    """
    Named-input processing endpoint (DAG scheduler format)

    Input:
        - inputs: dict of port_name -> NodeOutputInput
          - Look for key "image" with binary[0].ref (file path) or text (base64)
        - config: optional engine configuration

    Output:
        - NodeOutput: {"text": ..., "binary": [], "structured": null, "metadata": {...}}
    """
    start_time = time.time()

    try:
        try:
            credential_kind = CredentialKind(
                raw_request.headers.get(_CREDENTIAL_KIND_HEADER, CredentialKind.none.value)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid VLM credential kind") from exc
        credential = raw_request.headers.get(_CREDENTIAL_HEADER)
        if credential_kind is CredentialKind.none:
            credential = None
        elif not credential:
            raise HTTPException(status_code=400, detail="Missing VLM credential")

        engine = get_vlm_engine()

        # Find image input from named ports
        image_input = None
        for key in ("image", "images", "input"):
            if key in request.inputs:
                image_input = request.inputs[key]
                break

        if image_input is None and request.inputs:
            # Fallback: use first available input
            image_input = next(iter(request.inputs.values()))

        if image_input is None:
            raise HTTPException(status_code=400, detail="No input data provided")

        # Extract text input from "text" port
        text_content = None
        text_input = request.inputs.get("text")
        if text_input:
            text_content = text_input.text
            if not text_content and text_input.binary:
                ref = text_input.binary[0].get("ref", "")
                if ref and Path(ref).exists():
                    text_content = Path(ref).read_text(encoding="utf-8")

        config = dict(request.config or {})

        # Inject reference text into config so the engine can include it in the prompt
        if text_content:
            config["reference_text"] = text_content

        # Extract file path or base64 data
        file_path = None
        base64_data = None

        if image_input.binary and len(image_input.binary) > 1:
            all_texts = []
            request_ids: list[str] = []
            usage: list[dict] = []
            image_count = 0
            for b in image_input.binary:
                img_b64 = b.get("data") or ""
                if not img_b64:
                    ref = b.get("ref", "")
                    if ref and Path(ref).exists():
                        import base64 as _b64mod

                        img_b64 = _b64mod.b64encode(Path(ref).read_bytes()).decode("ascii")
                if not img_b64:
                    logger.warning("Skipping empty image entry in VLM multi-image input")
                    continue
                image_count += 1
                per_result = await asyncio.to_thread(
                    engine.process_base64,
                    img_b64,
                    config,
                    credential_kind=credential_kind,
                    credential=credential,
                )
                call_metadata = per_result.pop(_INTERNAL_METADATA_KEY, {})
                if isinstance(call_metadata, dict):
                    request_id = call_metadata.get("request_id")
                    if isinstance(request_id, str):
                        request_ids.append(request_id)
                    call_usage = call_metadata.get("usage")
                    if isinstance(call_usage, dict):
                        usage.append(call_usage)
                per_text = per_result.get("result", "")
                if not isinstance(per_text, str):
                    per_text = json.dumps(per_text, ensure_ascii=False)
                all_texts.append(per_text)

            processing_time = int((time.time() - start_time) * 1000)
            merged_text = "\n".join(all_texts)
            logger.info(
                "VLM request completed model=%s image_count=%d latency_ms=%d "
                "request_ids=%s usage=%s",
                config.get("model", _VLM_DEPLOYMENT_NAME),
                image_count,
                processing_time,
                request_ids,
                usage,
            )
            return {
                "text": merged_text,
                "binary": [],
                "structured": {"result": merged_text, "image_count": image_count},
                "metadata": {
                    "processing_time_ms": processing_time,
                    "model": config.get("model", _VLM_DEPLOYMENT_NAME),
                    "image_count": image_count,
                    "request_ids": request_ids,
                    "usage": usage,
                },
            }

        if image_input.binary:
            # Binary ref — file path on shared volume
            ref = image_input.binary[0].get("ref")
            data = image_input.binary[0].get("data")
            if ref and Path(ref).exists():
                file_path = ref
            elif data:
                base64_data = data
        elif image_input.text:
            # Text might be base64 encoded image
            base64_data = image_input.text

        if file_path:
            vlm_result = await asyncio.to_thread(
                engine.process_image,
                file_path,
                config,
                credential_kind=credential_kind,
                credential=credential,
            )
        elif base64_data:
            vlm_result = await asyncio.to_thread(
                engine.process_base64,
                base64_data,
                config,
                credential_kind=credential_kind,
                credential=credential,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="No image data found in input (no binary ref or base64)",
            )

        processing_time = int((time.time() - start_time) * 1000)
        call_metadata = vlm_result.pop(_INTERNAL_METADATA_KEY, {})
        logger.info(
            "VLM request completed model=%s latency_ms=%d request_id=%s usage=%s",
            config.get("model", _VLM_DEPLOYMENT_NAME),
            processing_time,
            call_metadata.get("request_id", "unknown")
            if isinstance(call_metadata, dict)
            else "unknown",
            call_metadata.get("usage", {}) if isinstance(call_metadata, dict) else {},
        )

        # Extract "result" as main text; store full JSON as structured
        result_text = vlm_result.get("result", "")
        if not isinstance(result_text, str):
            result_text = json.dumps(result_text, ensure_ascii=False)

        return {
            "text": result_text,
            "binary": [],
            "structured": vlm_result,
            "metadata": {
                "processing_time_ms": processing_time,
                "model": config.get("model", _VLM_DEPLOYMENT_NAME),
                **(call_metadata if isinstance(call_metadata, dict) else {}),
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("VLM request failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="VLM provider request failed") from exc


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
    )


@app.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Return engine configuration schema"""
    return ConfigResponse(
        engine_type="vlm",
        version="1.0.0",
        config_schema=VLM_CONFIG_SCHEMA,
    )


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint"""
    return {
        "service": "VLM Engine",
        "version": "1.0.0",
        "endpoints": {
            "process": "POST /process - Process image",
            "health": "GET /health - Basic health check",
            "config": "GET /config - Get engine configuration schema",
        },
    }
