"""Receive multipart uploads and persist to storage.

Sibling to InputFetcher — same DI pattern, streaming-to-disk via
LocalStorageAdapter, size ceiling + magic-byte validation.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from starlette.datastructures import UploadFile

from app.config import Settings, get_settings
from app.services.magic_bytes import MagicBytesError, validate_magic_bytes
from app.storage.local import LocalStorageAdapter, get_storage
from app.utils.path_utils import sanitize_filename


class UploadHandlerError(Exception):
    """Raised for any upload-phase failure (size, magic bytes, IO)."""


# Add a shared protocol only if another upload implementation needs it.
class UploadHandler:
    """Receive a multipart UploadFile, validate, and persist to storage."""

    def __init__(
        self,
        settings: Settings | None = None,
        storage: LocalStorageAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage or get_storage()

    async def receive_upload(self, file_part: UploadFile, run_id: str) -> str:
        """Sanitize filename, validate size + magic bytes, persist, return
        the saved absolute path.

        Raises UploadHandlerError on size ceiling breach or magic-byte
        mismatch.
        """
        safe_name = sanitize_filename(file_part.filename or f"{run_id}.bin")
        max_bytes = self._settings.input_upload_max_bytes

        # ---- layer 1: pre-read size check (best-effort via file_part.size) ----
        if file_part.size is not None and file_part.size > max_bytes:
            raise UploadHandlerError(f"Upload size exceeds limit ({max_bytes} bytes)")

        # ---- layer 2: streaming read with running byte counter ----
        async def bounded_chunks() -> AsyncIterator[bytes]:
            total = 0
            while True:
                chunk = await file_part.read(8192)
                if not chunk:
                    return
                total += len(chunk)
                if total > max_bytes:
                    raise UploadHandlerError(f"Upload size exceeds limit ({max_bytes} bytes)")
                yield chunk

        try:
            saved_path = await self._storage.save_stream(
                run_id, "original", safe_name, bounded_chunks()
            )
        except UploadHandlerError:
            await self._cleanup_partial(run_id, safe_name)
            raise

        # ---- magic-byte validation (read head from saved file) ----
        try:
            content = await self._storage.read_file(saved_path)
            head = content[:8]
            validate_magic_bytes(head, declared_mime=file_part.content_type)
        except MagicBytesError as exc:
            await self._cleanup_partial(run_id, safe_name)
            raise UploadHandlerError(str(exc)) from exc

        return saved_path

    async def _cleanup_partial(self, run_id: str, filename: str) -> None:
        """Best-effort delete of a partial upload; never raises."""
        try:
            task_dir = await self._storage.get_task_dir(run_id)
            partial = os.path.join(task_dir, "original", filename)
            if await self._storage.file_exists(partial):
                await self._storage.delete_file(partial)
        except Exception:  # noqa: BLE001
            # Cleanup is best-effort; every run writes to an isolated directory.
            pass
