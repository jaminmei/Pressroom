"""Public API Bearer auth dependency.

Authentication is implemented as a FastAPI ``Depends``
on individual routes, NOT global middleware. ``verify_api_key`` returns the
key's bound ``workflow_id`` and stashes it on ``request.state`` for downstream
handlers.

``HTTPBearer(auto_error=False)`` is used to register the Bearer scheme in
OpenAPI (renders the lock icon in /docs on endpoints depending on
``ApiKeyDep``) without raising on missing credentials — we surface our own
``UNAUTHORIZED`` envelope instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.public.error_response import (
    CODE_INVALID_API_KEY,
    CODE_SERVICE_UNAVAILABLE,
    CODE_UNAUTHORIZED,
    PublicApiError,
)
from app.services.api_key_service import ApiKeyService, ApiKeyVerificationError

# auto_error=False so missing/malformed Authorization falls through to our
# PublicApiError envelope (FastAPI's default would raise a plain 403).
_bearer_scheme = HTTPBearer(auto_error=False, description="Bearer API key")


@dataclass(frozen=True, slots=True)
class ApiKeyIdentity:
    api_key_id: str
    key_prefix: str
    workflow_id: str
    workspace_id: str | None


async def verify_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> ApiKeyIdentity:
    """Resolve the Bearer API key and return its bound identity.

    Side effects: sets verified identity fields on ``request.state`` for
    downstream handlers:

    - ``api_key_workflow_id`` — workflow_id the key is bound to.
    - ``api_key_id`` — the verified key's record id (used by upload rate
      limiter to bucket requests per key).
    """
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    else:
        # Fallback: parse raw header (covers non-standard clients / tests).
        raw = request.headers.get("Authorization")
        if raw is not None and raw.startswith("Bearer "):
            token = raw[len("Bearer ") :].strip()

    if not token:
        raise PublicApiError(
            status_code=401,
            code=CODE_UNAUTHORIZED,
            message="Missing or malformed Authorization header. Expected: Bearer <api_key>",
        )

    service: ApiKeyService | None = getattr(request.app.state, "api_key_service", None)
    if service is None:
        raise PublicApiError(
            status_code=503,
            code=CODE_SERVICE_UNAVAILABLE,
            message="API key service not initialised",
        )

    try:
        verified = await service.verify(token)
    except ApiKeyVerificationError:
        # Collapse invalid, revoked, and expired credentials into one public
        # error code. The service-specific reason is not exposed.
        raise PublicApiError(
            status_code=401,
            code=CODE_INVALID_API_KEY,
            message="Invalid or revoked API key",
        ) from None

    request.state.api_key_id = verified.id
    request.state.api_key_prefix = verified.key_prefix
    request.state.api_key_workflow_id = verified.workflow_id
    request.state.api_key_workspace_id = verified.workspace_id
    return ApiKeyIdentity(
        api_key_id=verified.id,
        key_prefix=verified.key_prefix,
        workflow_id=verified.workflow_id,
        workspace_id=verified.workspace_id,
    )


setattr(verify_api_key, "policy_kind", "public_api_key")  # noqa: B010


# Reusable type alias for Bearer-authenticated public endpoints:
#   async def handler(identity: ApiKeyDep, ...) -> ...: ...
ApiKeyDep = Annotated[ApiKeyIdentity, Depends(verify_api_key)]
