from __future__ import annotations

from typing import Any

from app.errors.error_codes import ERROR_CODE_STATUS_MAP, ErrorCode


class AppError(Exception):
    """Base application exception used by global FastAPI handlers."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code or ERROR_CODE_STATUS_MAP.get(error_code, 500)


class EngineError(AppError):
    """Engine-related error."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        *,
        engine_name: str,
        retry_count: int | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {"engine": engine_name}
        if retry_count is not None:
            merged_details["retry_count"] = retry_count
        if details:
            merged_details.update(details)

        super().__init__(
            error_code=error_code,
            message=message,
            details=merged_details,
            status_code=status_code,
        )


class ValidationError(AppError):
    """Input/workflow validation error."""


class InfraError(AppError):
    """Infrastructure-level error (DB/Redis/Celery/Storage)."""
