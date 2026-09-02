"""Server-only Agent Tool Gateway transport for the built-in Pi Extension."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from app.services.agent_tool_gateway import (
    _TOOL_GRANT_HEADER,
    AgentToolGateway,
    AgentToolGatewayError,
    error_envelope,
    require_agent_tool_gateway_grant,
)

router = APIRouter(prefix="/internal/agent-tools", tags=["internal-agent-tools"])
logger = logging.getLogger(__name__)
_grant_header = APIKeyHeader(name=_TOOL_GRANT_HEADER, auto_error=False)
setattr(_grant_header, "policy_kind", "internal_tool_gateway")  # noqa: B010


class ToolExecutionRequest(BaseModel):
    catalog_version: str
    operation: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


@router.post("/execute", include_in_schema=False)
async def execute_tool(
    payload: ToolExecutionRequest,
    request: Request,
    token: Annotated[str | None, Security(_grant_header)],
) -> JSONResponse:
    try:
        grant = require_agent_tool_gateway_grant(request.app, token)
        result = await AgentToolGateway(request.app).execute(
            grant=grant,
            catalog_version=payload.catalog_version,
            operation=payload.operation,
            args=payload.args,
            tool_call_id=payload.tool_call_id,
        )
        return JSONResponse(status_code=200, content=result)
    except AgentToolGatewayError as exc:
        return JSONResponse(status_code=409, content=error_envelope(exc.code, exc.message))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Agent Tool Gateway request failed error_type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_envelope("TOOL_GATEWAY_FAILED", "Agent tool execution failed"),
        )
