"""Public API error envelope: ``{error: {code, message, ...extra}}``.

The public API uses a single error shape for all failures. It is distinct
from the authenticated application API error format.

Self-check: see ``app/api/public/router.py``.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

# Common authentication and availability error codes for the public surface.
CODE_UNAUTHORIZED = "UNAUTHORIZED"
CODE_INVALID_API_KEY = "INVALID_API_KEY"
CODE_SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class PublicApiError(Exception):
    """Raised inside public routes; converted to the envelope by the handler.

    ``extra_fields`` become top-level keys of the ``error`` object.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **extra_fields: object,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra_fields = extra_fields


def public_error_response(
    status_code: int,
    code: str,
    message: str,
    **extra_fields: object,
) -> JSONResponse:
    """Build the standard ``{error: {...}}`` envelope as a JSONResponse."""
    content = {"error": {"code": code, "message": message, **extra_fields}}
    return JSONResponse(status_code=status_code, content=content)


async def public_api_exception_handler(
    request: Request,  # noqa: ARG001 - FastAPI handler signature
    exc: PublicApiError,
) -> JSONResponse:
    """Convert a raised ``PublicApiError`` into the standard envelope."""
    return public_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        **exc.extra_fields,
    )
