from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Unified API error response model."""

    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable message")
    details: dict[str, Any] | None = Field(default=None, description="Structured details")
    trace_id: str = Field(..., description="Request trace ID, format tr-{uuid}")


CANONICAL_ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    401: {"model": ErrorResponse, "description": "Authentication required"},
    403: {"model": ErrorResponse, "description": "Permission denied"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Request conflicts with current state"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
}


def canonical_error_responses() -> dict[int | str, dict[str, Any]]:
    responses: dict[int | str, dict[str, Any]] = {}
    responses.update(CANONICAL_ERROR_RESPONSES)
    return responses
