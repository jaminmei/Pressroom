from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.services.ssrf_guard import SsrfBlockedError, resolve_and_validate_provider
from app.services.ssrf_transport import provider_ssrf_safe_client


def _addr(ip: str, port: int = 443) -> list[tuple[object, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def test_private_provider_host_requires_explicit_opt_in() -> None:
    with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=_addr("10.0.0.8")):
        with pytest.raises(SsrfBlockedError, match="private"):
            resolve_and_validate_provider(
                "private.example",
                443,
                Settings(provider_allow_private_hosts=False),
            )
        assert (
            resolve_and_validate_provider(
                "private.example",
                443,
                Settings(provider_allow_private_hosts=True),
            )
            == "10.0.0.8"
        )


@pytest.mark.parametrize(
    "ip",
    ["169.254.169.254", "169.254.170.2", "100.100.100.200", "168.63.129.16"],
)
def test_metadata_is_blocked_even_when_private_hosts_are_allowed(ip: str) -> None:
    with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=_addr(ip)):
        with pytest.raises(SsrfBlockedError, match="permanently blocked"):
            resolve_and_validate_provider(
                "metadata.example",
                80,
                Settings(provider_allow_private_hosts=True),
            )


def test_mixed_dns_answers_fail_closed() -> None:
    mixed_metadata = _addr("93.184.216.34") + _addr("169.254.169.254")
    with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=mixed_metadata):
        with pytest.raises(SsrfBlockedError, match="permanently blocked"):
            resolve_and_validate_provider(
                "mixed.example",
                443,
                Settings(provider_allow_private_hosts=True),
            )

    mixed_private = _addr("93.184.216.34") + _addr("10.0.0.8")
    with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=mixed_private):
        with pytest.raises(SsrfBlockedError, match="private destination"):
            resolve_and_validate_provider(
                "mixed.example",
                443,
                Settings(provider_allow_private_hosts=False),
            )


@pytest.mark.asyncio
async def test_provider_transport_pins_validated_ip_and_preserves_host() -> None:
    requests: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with patch(
        "app.services.ssrf_guard.socket.getaddrinfo",
        return_value=_addr("93.184.216.34", 80),
    ):
        async with provider_ssrf_safe_client(
            Settings(provider_allow_private_hosts=False),
            inner=httpx.MockTransport(responder),
        ) as client:
            response = await client.get("http://provider.example/models")

    assert response.status_code == 200
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "provider.example"


@pytest.mark.asyncio
async def test_provider_redirect_is_not_followed_with_custom_credentials() -> None:
    requests: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data"},
            request=request,
        )

    with patch(
        "app.services.ssrf_guard.socket.getaddrinfo",
        return_value=_addr("93.184.216.34", 80),
    ):
        async with provider_ssrf_safe_client(
            Settings(provider_allow_private_hosts=True),
            inner=httpx.MockTransport(responder),
        ) as client:
            response = await client.get(
                "http://provider.example/start",
                headers={"api-key": "test-only-key"},
            )

    assert response.status_code == 302
    assert len(requests) == 1
    assert requests[0].headers["api-key"] == "test-only-key"
