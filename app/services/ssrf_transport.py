"""SSRF-safe httpx transport: pin connections to pre-validated IPs.

Implements the LangChain ``SSRFSafeTransport`` pattern adapted to this repo:

  1. ``handle_async_request`` resolves the request's host via
     ``ssrf_guard.resolve_and_validate`` (one ``socket.getaddrinfo`` call).
  2. If any resolved IP is blocked and not opted in → ``SsrfBlockedError``.
  3. The request URL is rewritten with ``copy_with(host=pinned_ip)`` so the
     connection lands on the pinned IP.
  4. The original hostname is preserved via two channels:
       - ``Host`` header is already set on the incoming request by httpx
         (rewriting the URL with ``copy_with`` does NOT touch headers).
       - For HTTPS, ``extensions["sni_hostname"]`` is set so httpcore uses
         the original hostname as ``server_hostname`` for the TLS handshake.
  5. Provider clients do not follow redirects. This prevents non-standard
     credential headers (for example Azure ``api-key``) from crossing origins.

The inner ``AsyncHTTPTransport`` does the actual I/O; this transport only
intercepts request routing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.ssrf_guard import (
    SsrfBlockedError,
    resolve_and_validate,
    resolve_and_validate_provider,
)

Resolver = Callable[[str, int, Settings | None], str]


def _port_for(url: httpx.URL) -> int:
    """Return the explicit port from the URL or the scheme default."""
    if url.port is not None:
        return url.port
    return 443 if url.scheme == "https" else 80


class SsrfSafeTransport(httpx.AsyncBaseTransport):
    """Wraps an inner ``AsyncHTTPTransport`` with DNS-resolve-then-pin.

    Every request — including each redirect hop — is re-resolved and
    re-validated before connect. The connection pins to the resolved IP,
    mitigating DNS rebinding between resolve and connect.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        inner: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = resolve_and_validate,
        **inner_kwargs: Any,
    ) -> None:
        self._settings = settings or get_settings()
        self._inner = inner or httpx.AsyncHTTPTransport(**inner_kwargs)
        self._resolver = resolver

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            # No host (e.g., relative URL) — let the inner transport surface
            # the appropriate error rather than inventing one.
            return await self._inner.handle_async_request(request)

        host_str = host
        port = _port_for(request.url)

        # Resolve synchronously inside a thread (getaddrinfo is blocking).
        # httpx's own transport runs getaddrinfo in its event loop too — this
        # matches that pattern. Result is cached by the OS resolver.
        pinned_ip = await asyncio.to_thread(self._resolver, host_str, port, self._settings)

        # Rewrite URL to use the pinned IP — copy_with leaves Host header and
        # path/query intact.
        pinned_url = request.url.copy_with(host=pinned_ip)

        # Preserve original hostname for SNI on HTTPS so the cert validates.
        # httpcore reads request.extensions["sni_hostname"] and passes it as
        # server_hostname to SSLContext.wrap_socket (httpcore/_async/connection.py:107).
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host_str

        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=request.headers,
            content=request.content,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def ssrf_safe_client(
    settings: Settings | None = None,
    *,
    timeout: httpx.Timeout | None = None,
    max_redirects: int = 5,
) -> httpx.AsyncClient:
    """Build an ``AsyncClient`` whose transport enforces the SSRF guard.

    Connect+read timeout defaults to ``INPUT_FETCH_TIMEOUT_SECONDS`` if not
    given explicitly. Redirect following is ON by design so each hop is
    re-validated; the count is capped at ``max_redirects``.
    """
    settings = settings or get_settings()
    if timeout is None:
        t = float(settings.input_fetch_timeout_seconds)
        timeout = httpx.Timeout(connect=t, read=t, write=t, pool=t)
    transport = SsrfSafeTransport(settings=settings)
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=True,
        max_redirects=max_redirects,
    )


def provider_ssrf_safe_client(
    settings: Settings | None = None,
    *,
    timeout: httpx.Timeout | float | None = None,
    verify: bool = True,
    inner: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build an async client enforcing the Provider endpoint policy."""

    settings = settings or get_settings()
    resolved_timeout: httpx.Timeout | float = 30.0 if timeout is None else timeout
    transport = SsrfSafeTransport(
        settings=settings,
        inner=inner,
        resolver=resolve_and_validate_provider,
        verify=verify,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=resolved_timeout,
        follow_redirects=False,
    )


__all__ = [
    "SsrfBlockedError",
    "SsrfSafeTransport",
    "provider_ssrf_safe_client",
    "ssrf_safe_client",
]
