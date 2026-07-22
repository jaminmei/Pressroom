from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from uuid import uuid4

from app.storage.utils import ensure_path_within_root
from app.utils.path_utils import sanitize_filename


class TestSetStorage:
    """Local filesystem storage rooted at {storage_root}/test_sets/{test_set_id}/documents/."""

    __test__ = False

    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.test_sets_root = self.storage_root / "test_sets"

    def _document_path(self, test_set_id: str, doc_id: str, filename: str) -> Path:
        safe_filename = sanitize_filename(filename)
        return self.test_sets_root / test_set_id / "documents" / f"{doc_id}_{safe_filename}"

    def _thumbnail_path(self, test_set_id: str, doc_id: str, size: int) -> Path:
        return self.test_sets_root / test_set_id / "thumbnails" / doc_id / f"{size}.webp"

    async def save_document(
        self,
        test_set_id: str,
        doc_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        target_path = self._document_path(test_set_id, doc_id, filename)
        resolved = ensure_path_within_root(target_path, self.test_sets_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: resolved.parent.mkdir(parents=True, exist_ok=True))
        await loop.run_in_executor(None, resolved.write_bytes, content)
        return str(resolved.relative_to(self.storage_root))

    async def read_document(self, storage_path: str) -> bytes:
        resolved = ensure_path_within_root(self.storage_root / storage_path, self.test_sets_root)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, resolved.read_bytes)

    async def read_thumbnail(self, test_set_id: str, doc_id: str, size: int) -> bytes | None:
        resolved = ensure_path_within_root(
            self._thumbnail_path(test_set_id, doc_id, size),
            self.test_sets_root,
        )
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, resolved.read_bytes)
        except FileNotFoundError:
            return None

    async def save_thumbnail(
        self,
        test_set_id: str,
        doc_id: str,
        size: int,
        content: bytes,
    ) -> None:
        resolved = ensure_path_within_root(
            self._thumbnail_path(test_set_id, doc_id, size),
            self.test_sets_root,
        )
        temporary = ensure_path_within_root(
            resolved.with_name(f".{resolved.name}.{uuid4().hex}.tmp"),
            self.test_sets_root,
        )

        def _write_atomically() -> None:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            try:
                temporary.write_bytes(content)
                os.replace(temporary, resolved)
            finally:
                temporary.unlink(missing_ok=True)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write_atomically)

    async def delete_document(self, storage_path: str) -> None:
        resolved = ensure_path_within_root(self.storage_root / storage_path, self.test_sets_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: resolved.unlink(missing_ok=True))

    async def delete_document_thumbnails(self, test_set_id: str, doc_id: str) -> None:
        thumbnail_dir = ensure_path_within_root(
            self._thumbnail_path(test_set_id, doc_id, 96).parent,
            self.test_sets_root,
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: shutil.rmtree(thumbnail_dir, ignore_errors=True),
        )

    async def delete_test_set(self, test_set_id: str) -> None:
        test_set_dir = ensure_path_within_root(
            self.test_sets_root / test_set_id, self.test_sets_root
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: shutil.rmtree(test_set_dir, ignore_errors=True))


TestSetStorageAdapter = TestSetStorage
