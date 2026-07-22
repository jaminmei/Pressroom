"""SSRF guard: IP classification and DNS resolve-and-validate.

Pure logic only — no network I/O. The transport layer (``ssrf_transport.py``)
calls ``resolve_and_validate`` to pin connections to a pre-checked IP.

Blocked ranges (default-deny; opt-in via ``INPUT_FETCH_ALLOW_PRIVATE_HOSTS=true``):
  - RFC1918 private (10/8, 172.16/12, 192.168/16) — ``is_private``
  - Loopback (127/8, ::1) — ``is_loopback``
  - Link-local (169.254/16, fe80::/10) — covers cloud-metadata 169.254.169.254
  - IPv6 unique-local (fc00::/7) — ``is_private``
  - Multicast, unspecified, reserved — ``is_private`` / ``is_reserved``

``ipaddress`` stdlib already classifies all of the above; we just need to
deny everything that is not a public, routable, unicast address.
"""

from __future__ import annotations

import ipaddress
import socket

from app.config import Settings, get_settings

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


class SsrfBlockedError(ValueError):
    """Raised when a resolved IP is in a blocked range and the host is not opted in."""


def is_blocked_ip(ip_str: str) -> bool:
    """True iff the IP is private, loopback, link-local, reserved, or multicast.

    Cloud-metadata endpoints (169.254.169.254 and similar) are caught by
    ``is_link_local`` — no special-case list needed. The ipaddress module
    classifies them all consistently across IPv4 and IPv6.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Not a parseable IP — treat as blocked (defensive; should not happen
        # since we feed this from getaddrinfo's sockaddr[0]).
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_permanently_blocked_provider_ip(ip_str: str) -> bool:
    """Return whether Provider traffic must never reach *ip_str*.

    Private and loopback ranges are intentionally not permanent blocks because
    deployments can explicitly opt into them. Platform metadata, link-local,
    multicast, unspecified, and reserved destinations are never bypassable.
    """

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or any(ip in network for network in _METADATA_NETWORKS if ip.version == network.version)
    )


def resolve_and_validate(
    host: str,
    port: int,
    settings: Settings | None = None,
) -> str:
    """Resolve host to an IP and validate it against the SSRF policy.

    Resolves via ``socket.getaddrinfo`` (one call), checks EVERY returned IP,
    and returns the first allowed IP. If all IPs are blocked and the operator
    has not opted in via ``INPUT_FETCH_ALLOW_PRIVATE_HOSTS``, raises
    ``SsrfBlockedError``.

    When ``INPUT_FETCH_ALLOW_PRIVATE_HOSTS=true``, blocked IPs are still
    reported back (returned) — the opt-in disables enforcement, not detection,
    so operators can see what their deployment is reaching into.
    """
    settings = settings or get_settings()
    allow_private = settings.input_fetch_allow_private_hosts

    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        # DNS failure — treat as a blocked/invalid host.
        raise SsrfBlockedError(f"DNS resolution failed for {host!r}: {exc}") from exc

    if not addrinfo:
        raise SsrfBlockedError(f"DNS returned no addresses for {host!r}")

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = str(sockaddr[0])
        if not is_blocked_ip(ip_str):
            return ip_str

    # All resolved IPs are blocked. Honor the opt-in if set.
    # Each addrinfo tuple is (family, type, proto, canonname, sockaddr);
    # sockaddr[0] is the IP string for both IPv4 and IPv6.
    blocked_list = [str(ai[4][0]) for ai in addrinfo]
    if allow_private:
        return blocked_list[0]

    raise SsrfBlockedError(
        f"All resolved IPs for {host!r} are blocked (private/loopback/link-local/"
        f"reserved/multicast): {blocked_list}. Set INPUT_FETCH_ALLOW_PRIVATE_HOSTS=true"
        " to opt in if this is a trusted-internal deployment."
    )


def resolve_and_validate_provider(
    host: str,
    port: int,
    settings: Settings | None = None,
) -> str:
    """Resolve and pin a Provider host under the Provider-specific policy."""

    settings = settings or get_settings()
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfBlockedError(f"DNS resolution failed for provider host {host!r}") from exc
    if not addrinfo:
        raise SsrfBlockedError(f"DNS returned no addresses for provider host {host!r}")

    allowed: list[str] = []
    permanently_blocked: list[str] = []
    policy_blocked: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = str(sockaddr[0])
        if is_permanently_blocked_provider_ip(ip_str):
            permanently_blocked.append(ip_str)
            continue
        ip = ipaddress.ip_address(ip_str)
        if settings.provider_allow_private_hosts or ip.is_global:
            allowed.append(ip_str)
        else:
            policy_blocked.append(ip_str)

    if permanently_blocked:
        raise SsrfBlockedError(f"Provider host {host!r} includes a permanently blocked destination")
    if policy_blocked:
        raise SsrfBlockedError(
            f"Provider host {host!r} includes a private destination; set "
            "PROVIDER_ALLOW_PRIVATE_HOSTS=true only after accepting the multi-tenant risk"
        )
    if allowed:
        return allowed[0]
    raise SsrfBlockedError(f"Provider host {host!r} returned no usable destinations")
