"""Internal model proxy — server-side only, not browser-facing.

Called by the Node Pi runtime to reach configured llm_api Provider endpoints.
Decrypts credentials only for an authorized invocation and forwards the
native protocol request through the SSRF-safe, no-redirect transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

from app.providers.auth import AuthResolver
from app.providers.models import ApiProtocol, ModelProviderRow, ProviderType
from app.providers.readiness import ANTHROPIC_VERSION
from app.services.ssrf_guard import SsrfBlockedError
from app.services.ssrf_transport import provider_ssrf_safe_client

router = APIRouter(prefix="/internal/proxy", tags=["internal-proxy"])
logger = logging.getLogger(__name__)

INTERNAL_PROXY_AUTH_HEADER = "X-DocConv-Proxy-Token"
_internal_proxy_token = APIKeyHeader(
    name=INTERNAL_PROXY_AUTH_HEADER,
    auto_error=False,
    scheme_name="InternalProxyToken",
)


@dataclass(frozen=True, slots=True)
class InternalProxyGrant:
    chatbox_session_id: str
    workspace_id: str
    provider_id: str


def issue_internal_proxy_grant(
    app: Any,
    *,
    chatbox_session_id: str,
    workspace_id: str,
    provider_id: str,
) -> str:
    """Issue one process-local grant for a server-owned Pi runtime session."""

    token = secrets.token_urlsafe(32)
    grants: dict[str, InternalProxyGrant] = getattr(app.state, "chatbox_proxy_grants", {})
    grants[token] = InternalProxyGrant(
        chatbox_session_id=chatbox_session_id,
        workspace_id=workspace_id,
        provider_id=provider_id,
    )
    app.state.chatbox_proxy_grants = grants
    return token


def revoke_internal_proxy_grants(app: Any, *, chatbox_session_id: str) -> None:
    """Revoke every process-local invocation grant owned by one chatbox session."""

    grants: dict[str, InternalProxyGrant] = getattr(app.state, "chatbox_proxy_grants", {})
    app.state.chatbox_proxy_grants = {
        token: grant
        for token, grant in grants.items()
        if grant.chatbox_session_id != chatbox_session_id
    }


def revoke_internal_proxy_grant(app: Any, token: str) -> None:
    """Revoke one transient invocation grant without touching a live Runtime grant."""

    grants: dict[str, InternalProxyGrant] = getattr(app.state, "chatbox_proxy_grants", {})
    grants.pop(token, None)


def _require_internal_proxy_grant(
    request: Request,
    provider_id: str,
    token: Annotated[str | None, Security(_internal_proxy_token)],
) -> InternalProxyGrant:
    grants: dict[str, InternalProxyGrant] = getattr(
        request.app.state,
        "chatbox_proxy_grants",
        {},
    )
    grant = grants.get(token) if token else None
    if grant is None or grant.provider_id != provider_id:
        raise HTTPException(status_code=401, detail="Invalid internal proxy authorization")
    return grant


setattr(_require_internal_proxy_grant, "policy_kind", "internal_proxy")  # noqa: B010


def _resource_url(provider: ModelProviderRow) -> str:
    base = provider.base_url.rstrip("/")
    match provider.api_protocol:
        case ApiProtocol.openai_chat_completions:
            return f"{base}/chat/completions"
        case ApiProtocol.openai_responses:
            return f"{base}/responses"
        case ApiProtocol.anthropic_messages:
            return f"{base}/messages"
        case None:
            raise HTTPException(status_code=400, detail="Provider has no api_protocol")


def _build_headers(protocol: ApiProtocol, token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if protocol == ApiProtocol.anthropic_messages:
        headers["x-api-key"] = token
        headers["anthropic-version"] = ANTHROPIC_VERSION
    else:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _shape_payload(
    protocol: ApiProtocol,
    model_id: str,
    incoming: dict[str, Any],
    *,
    model_max_tokens: int,
) -> dict[str, Any]:
    body = dict(incoming)
    body["model"] = model_id
    if protocol in {
        ApiProtocol.openai_chat_completions,
        ApiProtocol.openai_responses,
    }:
        body["store"] = False
    if protocol == ApiProtocol.openai_responses:
        body.pop("previous_response_id", None)
    if protocol == ApiProtocol.anthropic_messages and "max_tokens" not in body:
        body["max_tokens"] = model_max_tokens
    return body


class _UpstreamResponseStream:
    """Own an upstream response and close it on every downstream exit path."""

    def __init__(self, upstream: httpx.Response, client: httpx.AsyncClient) -> None:
        self._upstream = upstream
        self._client = client
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._iterator = self._iterate()

    def __aiter__(self) -> _UpstreamResponseStream:
        return self

    async def __anext__(self) -> bytes:
        return await anext(self._iterator)

    async def _iterate(self) -> AsyncGenerator[bytes, None]:
        try:
            # The proxy intentionally does not forward Content-Encoding. Yield
            # decoded bytes so downstream JSON/SSE consumers never receive a
            # compressed body mislabeled as plain content.
            async for chunk in self._upstream.aiter_bytes():
                yield chunk
        except httpx.RequestError as exc:
            # The HTTP response has already started, so this cannot be translated
            # into a new status code. Keep diagnostics free of URLs and bodies.
            logger.warning(
                "Internal Provider response stream failed error_type=%s",
                type(exc).__name__,
            )
            raise
        finally:
            await self._close_resources()

    async def aclose(self) -> None:
        try:
            await self._iterator.aclose()
        finally:
            await self._close_resources()

    async def _close_resources(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                await self._upstream.aclose()
            finally:
                await self._client.aclose()


def _stream_upstream_response(
    upstream: httpx.Response,
    client: httpx.AsyncClient,
) -> _UpstreamResponseStream:
    return _UpstreamResponseStream(upstream, client)


class _ManagedStreamingResponse(StreamingResponse):
    """Close the managed upstream even when ASGI send fails before background runs."""

    def __init__(
        self,
        body: _UpstreamResponseStream,
        *,
        status_code: int,
        headers: dict[str, str],
    ) -> None:
        self._managed_body = body
        super().__init__(
            body,
            status_code=status_code,
            headers=headers,
            background=BackgroundTask(body.aclose),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._managed_body.aclose()


@router.post("/invoke/{provider_id}")
async def invoke_provider(
    provider_id: str,
    request: Request,
    grant: Annotated[InternalProxyGrant, Depends(_require_internal_proxy_grant)],
) -> Response:
    """Forward a native protocol request to the configured Provider endpoint."""

    raw = await request.body()
    try:
        parsed = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    model_id = parsed.get("model_id")
    api_protocol_raw = parsed.get("api_protocol")
    incoming_payload = parsed.get("payload", {})
    if not isinstance(incoming_payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    if not isinstance(model_id, str) or not model_id.strip():
        raise HTTPException(
            status_code=400,
            detail="model_id must be a non-empty string",
        )
    if not api_protocol_raw:
        raise HTTPException(status_code=400, detail="api_protocol is required")

    try:
        api_protocol = ApiProtocol(api_protocol_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unsupported api_protocol: {api_protocol_raw}"
        ) from exc

    store = getattr(request.app.state, "provider_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Provider store not initialised")

    row = store.get_for_runtime(provider_id, grant.workspace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if row.provider_type != ProviderType.llm_api:
        raise HTTPException(status_code=400, detail="Proxy supports only llm_api providers")
    if row.api_protocol != api_protocol:
        raise HTTPException(status_code=400, detail="api_protocol does not match the provider")
    if row.model_max_tokens is None:
        raise HTTPException(status_code=409, detail="Provider model configuration is incomplete")

    auth = await AuthResolver(fernet=store.fernet).resolve(row)
    token = auth.credential
    if not token:
        raise HTTPException(status_code=500, detail="Provider credential missing")

    url = _resource_url(row)
    headers = _build_headers(api_protocol, token)
    body = _shape_payload(
        api_protocol,
        str(model_id),
        incoming_payload,
        model_max_tokens=row.model_max_tokens,
    )

    client = provider_ssrf_safe_client(timeout=httpx.Timeout(120.0, connect=10.0))
    try:
        upstream_request = client.build_request("POST", url, json=body, headers=headers)
        upstream = await client.send(upstream_request, stream=True)
    except SsrfBlockedError:
        await client.aclose()
        raise HTTPException(
            status_code=403, detail="Provider endpoint blocked by network policy"
        ) from None
    except httpx.RequestError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Provider request failed") from None

    content_type = upstream.headers.get("content-type", "application/json")
    response_body = _stream_upstream_response(upstream, client)
    return _ManagedStreamingResponse(
        response_body,
        status_code=upstream.status_code,
        headers={"content-type": content_type},
    )
