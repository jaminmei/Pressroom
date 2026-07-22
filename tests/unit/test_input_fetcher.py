"""Unit tests for InputFetcher + SSRF guard (Groups 1+2+3 of public-api-url-input).

Covers tasks 4.1-4.4:
  - 4.1 scheme detection (URL → fetch path; non-URL → passthrough)
  - 4.2 SSRF rejection matrix (loopback, RFC1918, link-local, 169.254.169.254;
       opt-in flag permits private hosts)
  - 4.3 size limit mid-stream abort + timeout on non-responsive host
  - 4.4 happy path with mocked httpx — file written to per-run path, returned
       path is os.path.isfile()-true

httpx is mocked via httpx.MockTransport injected as the SSRF transport's
``inner`` so the SSRF resolve+validate+pin path runs for real (against
getaddrinfo output) but the wire I/O is intercepted.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.services.input_fetcher import (
    InputFetcher,
    InputFetchError,
    _filename_from_url,
    _is_remote_url,
)
from app.services.ssrf_guard import SsrfBlockedError, is_blocked_ip, resolve_and_validate
from app.services.ssrf_transport import SsrfSafeTransport
from app.storage.local import LocalStorageAdapter

# ---------- 4.1 scheme detection ----------


class TestSchemeDetection:
    def test_url_schemes_detected(self) -> None:
        for url in (
            "http://example.com/a.pdf",
            "https://example.com/a.pdf",
            "HTTP://EXAMPLE.COM/A.PDF",
            "Https://Example.Com/A.PDF",
        ):
            assert _is_remote_url(url) is True, url

    def test_non_url_passes_through(self) -> None:
        for value in (
            "/app/storage/x.pdf",
            "/app/storage/tasks/r1/original/y.png",
            "relative/path.pdf",
            "",
            "ftp://example.com/a.pdf",
            "file:///etc/passwd",
        ):
            assert _is_remote_url(value) is False, value

    @pytest.mark.asyncio()
    async def test_local_path_returned_unchanged(self, tmp_path: Path) -> None:
        fetcher = InputFetcher(storage=LocalStorageAdapter(storage_root=str(tmp_path)))
        local = "/app/storage/tasks/r1/original/y.pdf"
        result = await fetcher.resolve_input_file(local, "r1")
        assert result == local


class TestFilenameDerivation:
    def test_filename_from_url_path(self) -> None:
        assert _filename_from_url("https://example.com/invoice.pdf") == "invoice.pdf"
        assert _filename_from_url("https://example.com/a/b/c/doc.png") == "doc.png"

    def test_filename_from_url_no_extension(self) -> None:
        assert _filename_from_url("https://example.com/justname") == "justname"

    def test_filename_from_url_empty_path(self) -> None:
        assert _filename_from_url("https://example.com/") == "input"
        assert _filename_from_url("https://example.com") == "input"

    def test_filename_from_url_traversal_stripped(self) -> None:
        # Path traversal must not escape the per-run dir.
        name = _filename_from_url("https://example.com/../etc/passwd")
        assert ".." not in name
        assert "/" not in name
        assert name == "passwd"

    def test_filename_from_url_encoded(self) -> None:
        assert _filename_from_url("https://example.com/a%20b.pdf") == "a b.pdf"


# ---------- 4.2 SSRF rejection matrix ----------


class TestSsrfBlockedIpMatrix:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "127.255.255.255",  # loopback
            "::1",  # IPv6 loopback
            "10.0.0.1",
            "10.255.255.255",  # RFC1918 10/8
            "192.168.1.1",
            "192.168.0.0",  # RFC1918 192.168/16
            "172.16.0.1",
            "172.31.255.255",  # RFC1918 172.16/12
            "169.254.169.254",
            "169.254.0.1",  # link-local / cloud-metadata
            "fe80::1",  # IPv6 link-local
            "fc00::1",
            "fd00::1",  # IPv6 unique-local
            "224.0.0.1",  # multicast
            "0.0.0.0",  # unspecified
            "240.0.0.1",  # reserved
        ],
    )
    def test_blocked_ip_classified(self, ip: str) -> None:
        assert is_blocked_ip(ip) is True, ip

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "172.32.0.1"])
    def test_public_ip_not_blocked(self, ip: str) -> None:
        assert is_blocked_ip(ip) is False, ip

    def test_unparseable_ip_treated_as_blocked(self) -> None:
        assert is_blocked_ip("not-an-ip") is True


class TestSsrfResolveDefaultDeny:
    def test_loopback_literal_blocked(self) -> None:
        with pytest.raises(SsrfBlockedError):
            resolve_and_validate("127.0.0.1", 80)

    def test_ipv6_loopback_literal_blocked(self) -> None:
        with pytest.raises(SsrfBlockedError):
            resolve_and_validate("::1", 80)

    def test_metadata_literal_blocked(self) -> None:
        # 169.254.169.254 — cloud metadata endpoint
        with pytest.raises(SsrfBlockedError):
            resolve_and_validate("169.254.169.254", 80)

    def test_dns_failure_blocked(self) -> None:
        # .invalid is reserved by RFC 2606 — guaranteed DNS NXDOMAIN
        with pytest.raises(SsrfBlockedError, match="DNS resolution failed"):
            resolve_and_validate("nonexistent.invalid", 80)

    def test_opt_in_permits_private_host(self) -> None:
        # Monkey-patch getaddrinfo to return a private IP deterministically
        # (avoids relying on real DNS for a private range).
        fake_addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.42", 80)),
        ]
        settings = Settings(input_fetch_allow_private_hosts=True)
        with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_addrinfo):
            ip = resolve_and_validate("private.example.com", 80, settings=settings)
        assert ip == "10.0.0.42"

    def test_opt_in_still_blocks_when_mixed_ips_with_default_deny(self) -> None:
        # When allow_private=False (default) and host returns mixed public+private,
        # the first PUBLIC ip is returned (the validator should not just take the
        # first addrinfo entry).
        fake_addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.42", 80)),  # private
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),  # public
        ]
        with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_addrinfo):
            ip = resolve_and_validate("mixed.example.com", 80)
        assert ip == "93.184.216.34"


class TestSsrfAtFetcherLevel:
    """SSRF must surface as InputFetchError so the handler can map to 400."""

    @pytest.mark.asyncio()
    async def test_loopback_url_blocked_at_fetcher(self, tmp_path: Path) -> None:
        fetcher = InputFetcher(storage=LocalStorageAdapter(storage_root=str(tmp_path)))
        with pytest.raises(InputFetchError, match="SSRF"):
            await fetcher.resolve_input_file("http://127.0.0.1:8000/admin", "r1")

    @pytest.mark.asyncio()
    async def test_metadata_url_blocked_at_fetcher(self, tmp_path: Path) -> None:
        fetcher = InputFetcher(storage=LocalStorageAdapter(storage_root=str(tmp_path)))
        with pytest.raises(InputFetchError, match="SSRF"):
            await fetcher.resolve_input_file("http://169.254.169.254/latest/meta-data/", "r1")

    @pytest.mark.asyncio()
    async def test_rfc1918_blocked_at_fetcher(self, tmp_path: Path) -> None:
        fetcher = InputFetcher(storage=LocalStorageAdapter(storage_root=str(tmp_path)))
        with pytest.raises(InputFetchError, match="SSRF"):
            await fetcher.resolve_input_file("http://10.0.0.1/x", "r1")


# ---------- 4.3 size limit + timeout ----------


def _build_fetcher_with_mocked_inner(
    tmp_path: Path,
    responder: object,
    *,
    max_bytes: int = 104857600,
    timeout_seconds: int = 30,
    allow_private: bool = False,
) -> tuple[InputFetcher, httpx.AsyncClient]:
    """Wire up an InputFetcher whose SSRF transport uses a MockTransport inner.

    The SSRF resolve+validate+pin path runs for real; only wire I/O is mocked.
    """
    settings = Settings(
        storage_root=str(tmp_path),
        input_fetch_max_bytes=max_bytes,
        input_fetch_timeout_seconds=timeout_seconds,
        input_fetch_allow_private_hosts=allow_private,
    )
    storage = LocalStorageAdapter(storage_root=str(tmp_path))
    fetcher = InputFetcher(settings=settings, storage=storage)

    # Monkey-patch ssrf_safe_client to return a client whose transport is our
    # SSRF wrapper around a MockTransport. getaddrinfo is patched to return a
    # fixed public IP so resolve_and_validate passes.
    inner = httpx.MockTransport(responder)
    transport = SsrfSafeTransport(settings=settings, inner=inner)
    t = float(timeout_seconds)
    client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(connect=t, read=t, write=t, pool=t),
        follow_redirects=True,
        max_redirects=5,
    )

    orig_client_factory = None
    import app.services.input_fetcher as mod

    class _CM:
        async def __aenter__(self) -> httpx.AsyncClient:
            return client

        async def __aexit__(self, *args: object) -> bool:
            return False

    orig_client_factory = mod.ssrf_safe_client
    mod.ssrf_safe_client = lambda *a, **k: _CM()

    fake_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]
    patcher = patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_addrinfo)
    patcher.start()

    return fetcher, client, (mod, orig_client_factory, patcher)


def _teardown_mock(state: tuple) -> None:
    mod, orig, patcher = state
    mod.ssrf_safe_client = orig
    patcher.stop()


class TestSizeLimit:
    @pytest.mark.asyncio()
    async def test_oversize_aborts_mid_stream(self, tmp_path: Path) -> None:
        # Server claims 1MB but we cap at 10 bytes.
        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 1024)

        fetcher, _, state = _build_fetcher_with_mocked_inner(tmp_path, responder, max_bytes=10)
        try:
            with pytest.raises(InputFetchError, match="MAX_BYTES|exceeded"):
                await fetcher.resolve_input_file("https://example.com/big.bin", "run_over")
            # Partial file must be cleaned up.
            task_dir = tmp_path / "tasks" / "run_over" / "original"
            if task_dir.is_dir():
                assert not any(task_dir.iterdir()), "partial file leaked"
        finally:
            _teardown_mock(state)


class TestTimeout:
    @pytest.mark.asyncio()
    async def test_timeout_on_nonresponsive_host(self, tmp_path: Path) -> None:
        # Responder raises a read timeout — must surface as InputFetchError.
        def responder(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated read timeout", request=request)

        fetcher, _, state = _build_fetcher_with_mocked_inner(tmp_path, responder, timeout_seconds=1)
        try:
            with pytest.raises(InputFetchError, match="timed out|timeout"):
                await fetcher.resolve_input_file("https://example.com/slow", "run_timeout")
        finally:
            _teardown_mock(state)


# ---------- 4.4 happy path with mocked httpx ----------


class TestHappyPath:
    @pytest.mark.asyncio()
    async def test_file_written_and_path_returned(self, tmp_path: Path) -> None:
        body = b"PDF-1.4 ...fake pdf bytes..."

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        fetcher, _, state = _build_fetcher_with_mocked_inner(tmp_path, responder)
        try:
            path = await fetcher.resolve_input_file("https://example.com/invoice.pdf", "run_happy")
            # Returned path must be a real file on disk.
            assert os.path.isfile(path), f"not a file: {path}"
            # File content must match.
            with open(path, "rb") as f:
                assert f.read() == body
            # Path layout: /tasks/{run_id}/original/{filename}
            assert "tasks" in path
            assert os.sep + "run_happy" + os.sep in path or "/run_happy/" in path
            assert path.endswith(os.sep + "invoice.pdf") or path.endswith("/invoice.pdf")
        finally:
            _teardown_mock(state)

    @pytest.mark.asyncio()
    async def test_http_error_status_raises(self, tmp_path: Path) -> None:
        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b"not found")

        fetcher, _, state = _build_fetcher_with_mocked_inner(tmp_path, responder)
        try:
            with pytest.raises(InputFetchError, match="HTTP 404"):
                await fetcher.resolve_input_file("https://example.com/missing", "run_404")
        finally:
            _teardown_mock(state)


# ---------- 4.5-style: redirect re-validation (moved here from verify self-check) ----------


class TestRedirectRevalidation:
    @pytest.mark.asyncio()
    async def test_redirect_to_loopback_blocked(self, tmp_path: Path) -> None:
        # First hop resolves to public IP (mocked getaddrinfo), inner returns
        # 302 → 127.0.0.1. The redirect target must be re-resolved and blocked.
        from app.services.ssrf_transport import SsrfSafeTransport

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/pwned"})

        settings = Settings(storage_root=str(tmp_path))
        inner = httpx.MockTransport(responder)
        transport = SsrfSafeTransport(settings=settings, inner=inner)
        client = httpx.AsyncClient(transport=transport, follow_redirects=True, max_redirects=5)

        # Patch getaddrinfo: dns.google → public; 127.0.0.1 → loopback (real).
        dns_call_count = {"n": 0}
        real_getaddrinfo = socket.getaddrinfo  # capture before patching

        def fake_getaddrinfo(host: str, port: int, *args: object, **kwargs: object):
            dns_call_count["n"] += 1
            if host == "127.0.0.1":
                # Real resolution — loopback. Use the saved reference so the
                # active patch doesn't recurse into fake_getaddrinfo.
                return real_getaddrinfo(host, port, type=socket.SOCK_STREAM)
            # Pretend dns.google resolves to a public IP
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        with patch("app.services.ssrf_guard.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with pytest.raises(Exception) as exc_info:
                # Use the client directly so we exercise the transport chain
                await client.get("https://dns.google/start")
            # SSRFBlockedError OR InputFetchError(SSRF) depending on layer
            assert "SSRF" in str(exc_info.value) or "blocked" in str(exc_info.value).lower()
        await client.aclose()
