"""Resolve inputs.file values for the public /run API.

Local in-container paths pass through unchanged (preserves the existing
DAG-scheduler contract). http(s):// URLs are downloaded to the shared storage
volume and the resulting local absolute path is returned.

The fetch enforces three guards before any byte is written to disk:
  - SSRF: ``ssrf_transport.SsrfSafeTransport`` resolves the host via
    ``socket.getaddrinfo``, validates every IP against the blocked ranges
    (RFC1918 / loopback / link-local / reserved / multicast — cloud-metadata
    ``169.254.169.254`` is caught by ``is_link_local``), and pins the
    connection to the resolved IP. Each redirect hop is re-resolved and
    re-validated automatically by httpx's redirect loop.
  - Size: ``INPUT_FETCH_MAX_BYTES`` hard ceiling; the stream is aborted
    mid-flight the moment accumulated bytes exceed it.
  - Time: connect+read timeout from ``INPUT_FETCH_TIMEOUT_SECONDS``.

All fetch failures (SSRF, DNS, HTTP error, oversized, timeout) surface as
``InputFetchError`` so the public handler can map them to ``400 INVALID_INPUT``
before any DAG run is started.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import unquote, urlparse

import httpx

from app.config import Settings, get_settings
from app.services.ssrf_guard import SsrfBlockedError
from app.services.ssrf_transport import ssrf_safe_client
from app.storage.local import LocalStorageAdapter, get_storage

_URL_SCHEMES = ("http://", "https://")


class InputFetchError(Exception):
    """Raised for any fetch-phase failure (URL parse, SSRF, HTTP, size, timeout).

    The public /run handler maps this to ``400 INVALID_INPUT``.
    """


def _is_remote_url(value: str) -> bool:
    """True iff value starts with http:// or https:// (case-insensitive)."""
    return value.lower().startswith(_URL_SCHEMES)


def _filename_from_url(url: str) -> str:
    """Derive a safe filename from the URL path; fall back to 'input'.

    Uses the final URL path component and strips traversal tokens.
    """
    path = unquote(urlparse(url).path)
    name = path.rsplit("/", 1)[-1].strip()
    name = name.replace("..", "").replace("/", "").strip(".") or "input"
    return name or "input"


class InputFetcher:
    """Resolve inputs.file values to a local absolute path.

    Local paths are returned verbatim. Remote URLs are downloaded into the
    run's storage subdir as ``/tasks/{run_id}/original/{filename}`` and the
    absolute path is returned. Failures raise ``InputFetchError`` so the
    caller (public /run handler) can map them to ``400 INVALID_INPUT`` before
    the DAG starts.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        storage: LocalStorageAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage or get_storage()

    async def resolve_input_file(self, value: str, run_id: str) -> str:
        """Return a local absolute path for the given inputs.file value.

        - Non-URL values: returned unchanged (local passthrough).
        - http(s):// values: downloaded to per-run storage, local path returned.
        """
        if not _is_remote_url(value):
            return value
        filename = _filename_from_url(value)
        path = await self._download_to_storage(value, run_id, filename)
        return path

    async def _download_to_storage(
        self,
        url: str,
        run_id: str,
        filename: str,
    ) -> str:
        """Stream url to per-run storage with all guards applied.

        Returns the saved absolute path. Raises InputFetchError on any failure.
        """
        max_bytes = self._settings.input_fetch_max_bytes

        try:
            async with ssrf_safe_client(self._settings) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        raise InputFetchError(f"Remote returned HTTP {response.status_code}")

                    async def bounded_chunks() -> AsyncIterator[bytes]:
                        # Local generator: yields chunks until the ceiling is
                        # crossed, then raises to abort the stream and the
                        # underlying connection (context manager closes it).
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise InputFetchError(
                                    f"Remote exceeded INPUT_FETCH_MAX_BYTES "
                                    f"({max_bytes} bytes) after {total}"
                                )
                            yield chunk

                    try:
                        saved_path = await self._storage.save_stream(
                            run_id, "original", filename, bounded_chunks()
                        )
                    except InputFetchError:
                        # Stream aborted mid-write: clean up the partial file
                        # so a retry doesn't see a truncated artifact.
                        await self._cleanup_partial(run_id, filename)
                        raise
                    return saved_path
        except SsrfBlockedError as exc:
            raise InputFetchError(f"SSRF guard rejected host: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise InputFetchError(
                f"Fetch timed out within {self._settings.input_fetch_timeout_seconds}s: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise InputFetchError(f"Fetch failed: {exc}") from exc

    async def _cleanup_partial(self, run_id: str, filename: str) -> None:
        """Best-effort delete of a partial download; never raises."""
        try:
            task_dir = await self._storage.get_task_dir(run_id)
            partial = os.path.join(task_dir, "original", filename)
            if await self._storage.file_exists(partial):
                await self._storage.delete_file(partial)
        except Exception:
            # Cleanup is best-effort; the next run writes a fresh file under
            # a new run_id anyway (per-run isolation).
            pass
