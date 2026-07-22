"""Error handling primitives for unified API error responses."""

from app.errors.error_codes import ERROR_CODE_STATUS_MAP, ErrorCode, resolve_status_code
from app.errors.error_response import ErrorResponse
from app.errors.exceptions import AppError, EngineError, InfraError, ValidationError
from app.errors.handlers import register_exception_handlers
from app.errors.retry import RETRYABLE_ENGINE_ERRORS, RetryConfig, RetryState, retry_with_backoff

__all__ = [
    "AppError",
    "EngineError",
    "ErrorCode",
    "ERROR_CODE_STATUS_MAP",
    "ErrorResponse",
    "InfraError",
    "RETRYABLE_ENGINE_ERRORS",
    "RetryConfig",
    "RetryState",
    "ValidationError",
    "register_exception_handlers",
    "retry_with_backoff",
    "resolve_status_code",
]
