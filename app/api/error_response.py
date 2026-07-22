"""Spec-compliant error response helper (09-error-handling.md section 1.1)."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.errors import ERROR_CODE_STATUS_MAP, ErrorCode
from app.errors.handlers import build_error_response, create_trace_id


def _normalize_error_code(code: str) -> ErrorCode | None:
    try:
        return ErrorCode(code)
    except ValueError:
        return None


def error_response(
    status_code: int | None,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    trace_id = create_trace_id()
    enum_code = _normalize_error_code(error_code)
    resolved_status = status_code
    if resolved_status is None and enum_code is not None:
        resolved_status = ERROR_CODE_STATUS_MAP[enum_code]
    if resolved_status is None:
        resolved_status = 500

    return build_error_response(
        status_code=resolved_status,
        error_code=enum_code.value if enum_code is not None else error_code,
        message=message,
        details=details,
        trace_id=trace_id,
    )
