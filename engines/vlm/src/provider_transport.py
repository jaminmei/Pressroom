"""DNS-pinned outbound transport for user-configured VLM providers."""

from __future__ import annotations

import ipaddress
import os
import socket

import httpx

_METADATA_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "169.254.169.254/32",
        "169.254.170.2/32",
        "100.100.100.200/32",
        "168.63.129.16/32",
        "192.0.0.192/32",
        "fd00:ec2::254/128",
    )
)


class ProviderAddressBlockedError(ValueError):
    """Raised when a provider host resolves only to forbidden addresses."""


def private_hosts_allowed() -> bool:
    return os.getenv("PROVIDER_ALLOW_PRIVATE_HOSTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_allowed_provider_ip(ip_text: str, *, allow_private: bool) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if _is_permanently_blocked(ip):
        return False
    return allow_private or ip.is_global


def _is_permanently_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or any(ip in network for network in _METADATA_NETWORKS if ip.version == network.version)
    )


def resolve_provider_ip(host: str, port: int, *, allow_private: bool) -> str:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderAddressBlockedError("Provider host could not be resolved") from exc

    if not addresses:
        raise ProviderAddressBlockedError("Provider host returned no addresses")

    candidates: list[tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address]] = []
    for _family, _type, _proto, _canonname, sockaddr in addresses:
        candidate = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError as exc:
            raise ProviderAddressBlockedError("Provider host returned an invalid address") from exc
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        candidates.append((candidate, ip))

    # Fail closed for the complete answer set. This prevents a mixed DNS
    # answer from using its public address to mask a metadata/private target.
    if any(_is_permanently_blocked(ip) for _, ip in candidates):
        raise ProviderAddressBlockedError("Provider address is permanently blocked")
    if not allow_private and any(not ip.is_global for _, ip in candidates):
        raise ProviderAddressBlockedError("Provider private address is blocked")
    return candidates[0][0]


class ProviderSafeTransport(httpx.BaseTransport):
    """Validate and pin DNS for every request, including redirect hops."""

    def __init__(
        self,
        *,
        verify: bool = True,
        allow_private: bool | None = None,
        inner: httpx.BaseTransport | None = None,
    ) -> None:
        self._allow_private = private_hosts_allowed() if allow_private is None else allow_private
        self._inner = inner or httpx.HTTPTransport(verify=verify)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise ProviderAddressBlockedError("Provider URL has no host")
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        pinned_ip = resolve_provider_ip(host, port, allow_private=self._allow_private)

        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host.encode("ascii")
        pinned_request = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=pinned_ip),
            headers=request.headers,
            content=request.content,
            extensions=extensions,
        )
        return self._inner.handle_request(pinned_request)

    def close(self) -> None:
        self._inner.close()


def provider_http_client(
    *,
    verify: bool,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 120.0,
) -> httpx.Client:
    safe_transport: httpx.BaseTransport
    if transport is None:
        safe_transport = ProviderSafeTransport(verify=verify)
    else:
        safe_transport = transport
    return httpx.Client(
        transport=safe_transport,
        timeout=timeout,
        # Never forward Azure's non-standard api-key header across origins.
        follow_redirects=False,
    )


__all__ = [
    "ProviderAddressBlockedError",
    "ProviderSafeTransport",
    "is_allowed_provider_ip",
    "private_hosts_allowed",
    "provider_http_client",
    "resolve_provider_ip",
]
