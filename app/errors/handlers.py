from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import JsonValue

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import AppError
from app.models.workspace_api import ErrorEnvelope

logger = logging.getLogger(__name__)


def create_trace_id() -> str:
    return f"tr-{uuid.uuid4()}"


def build_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    trace_id: str,
    details: dict[str, JsonValue] | None = None,
) -> JSONResponse:
    payload = ErrorEnvelope.model_validate(
        {
            "error_code": error_code,
            "message": message,
            "details": details,
            "trace_id": trace_id,
        }
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        trace_id = create_trace_id()
        return build_error_response(
            status_code=exc.status_code,
            error_code=exc.error_code.value,
            message=exc.message,
            details=exc.details,
            trace_id=trace_id,
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> Response:
        if request.url.path.startswith("/api/v1"):
            return await default_http_exception_handler(request, exc)
        message = str(exc.detail)
        error_code = _http_error_code(exc.status_code, message)
        details: dict[str, JsonValue] | None = (
            {"required_capability": message.removesuffix(" required")}
            if error_code is ErrorCode.REQUIRED_CAPABILITY_MISSING
            else None
        )
        return build_error_response(
            status_code=exc.status_code,
            error_code=error_code.value,
            message=_safe_message(error_code, message),
            details=details,
            trace_id=create_trace_id(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.startswith("/api/v1"):
            return await default_validation_exception_handler(request, exc)
        return build_error_response(
            status_code=422,
            error_code=ErrorCode.REQUEST_VALIDATION_FAILED.value,
            message="Request validation failed.",
            details={"errors": jsonable_encoder(exc.errors())},
            trace_id=create_trace_id(),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = create_trace_id()
        logger.error(
            "Unhandled error trace_id=%s method=%s error_type=%s",
            trace_id,
            request.method,
            type(exc).__name__,
        )
        return build_error_response(
            status_code=500,
            error_code=ErrorCode.INTERNAL_ERROR.value,
            message="An unexpected error occurred. Please contact support with the trace_id.",
            details=None,
            trace_id=trace_id,
        )


def _http_error_code(status_code: int, message: str) -> ErrorCode:
    lowered = message.lower()
    if status_code == 401:
        return ErrorCode.AUTH_REQUIRED
    if status_code == 403:
        return (
            ErrorCode.REQUIRED_CAPABILITY_MISSING
            if lowered.endswith(" required")
            else ErrorCode.WORKSPACE_FORBIDDEN
        )
    if status_code == 404:
        if lowered.startswith("workspace"):
            return ErrorCode.WORKSPACE_NOT_FOUND
        if lowered.startswith("provider"):
            return ErrorCode.PROVIDER_NOT_FOUND
        if lowered.startswith("file"):
            return ErrorCode.FILE_NOT_FOUND
        return ErrorCode.RESOURCE_NOT_FOUND
    if status_code == 409:
        return (
            ErrorCode.WORKSPACE_NOT_EMPTY
            if "delete workspace with" in lowered or "workspace still owns" in lowered
            else ErrorCode.REQUEST_CONFLICT
        )
    if status_code == 415:
        return ErrorCode.UNSUPPORTED_FORMAT
    if status_code == 422:
        return ErrorCode.REQUEST_VALIDATION_FAILED
    return ErrorCode.INTERNAL_ERROR


def _safe_message(error_code: ErrorCode, message: str) -> str:
    if error_code is ErrorCode.WORKSPACE_NOT_FOUND:
        return "Workspace not found."
    if error_code is ErrorCode.PROVIDER_NOT_FOUND:
        return "Provider not found."
    if error_code is ErrorCode.FILE_NOT_FOUND:
        return "File not found."
    if error_code is ErrorCode.RESOURCE_NOT_FOUND:
        return "Resource not found."
    if error_code is ErrorCode.REQUIRED_CAPABILITY_MISSING:
        return "Required capability is missing."
    if error_code is ErrorCode.WORKSPACE_NOT_EMPTY:
        return "Workspace still owns resources."
    return message
