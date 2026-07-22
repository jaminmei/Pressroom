from __future__ import annotations

import asyncio
import shutil
from functools import lru_cache
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from app.storage.base import StorageAdapter
from app.storage.utils import ensure_path_within_root


class LocalStorageAdapter(StorageAdapter):
    """Local filesystem storage rooted at {storage_root}/tasks/{task_id}/..."""

    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.tasks_root = self.storage_root / "tasks"

    def _validate_path_within(self, path: Path, root: Path) -> Path:
        """Ensure resolved path is within the allowed root directory."""
        return ensure_path_within_root(path, root)

    async def save_file(self, task_id: str, category: str, filename: str, content: bytes) -> str:
        task_dir = Path(await self.get_task_dir(task_id))
        target_path = task_dir / category / filename
        resolved = self._validate_path_within(target_path, self.tasks_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: resolved.parent.mkdir(parents=True, exist_ok=True))
        await loop.run_in_executor(None, resolved.write_bytes, content)
        return str(resolved)

    async def save_stream(
        self,
        task_id: str,
        category: str,
        filename: str,
        stream: AsyncIterator[bytes],
    ) -> str:
        """Stream chunks into the target file, creating parent dirs first.

        The caller is responsible for byte-ceiling enforcement — when it
        detects the ceiling is exceeded, it should stop iterating ``stream``
        and raise; the partial file left behind is the caller's to clean up
        (or to keep, depending on policy).
        """
        task_dir = Path(await self.get_task_dir(task_id))
        target_path = task_dir / category / filename
        resolved = self._validate_path_within(target_path, self.tasks_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: resolved.parent.mkdir(parents=True, exist_ok=True))

        # Open once in a thread, then write each chunk as it arrives.
        # Blocking file I/O on the executor keeps the event loop responsive.
        def _open() -> BinaryIO:
            return open(resolved, "wb")

        f = await loop.run_in_executor(None, _open)
        try:
            async for chunk in stream:
                await loop.run_in_executor(None, f.write, chunk)
        finally:
            await loop.run_in_executor(None, f.close)
        return str(resolved)

    async def read_file(self, file_path: str) -> bytes:
        path = Path(file_path)
        # If file_path is relative, resolve it against storage_root
        if not path.is_absolute():
            path = self.storage_root / path
        resolved = self._validate_path_within(path, self.storage_root)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, resolved.read_bytes)

    async def delete_file(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.is_absolute():
            path = self.storage_root / path
        resolved = self._validate_path_within(path, self.storage_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: resolved.unlink(missing_ok=True))

    async def file_exists(self, file_path: str) -> bool:
        path = Path(file_path)
        if not path.is_absolute():
            path = self.storage_root / path
        resolved = self._validate_path_within(path, self.storage_root)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, resolved.exists)

    async def get_task_dir(self, task_id: str) -> str:
        return str(self.tasks_root / task_id)

    async def delete_task(self, task_id: str) -> None:
        task_dir = Path(await self.get_task_dir(task_id))
        self._validate_path_within(task_dir, self.tasks_root)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: shutil.rmtree(task_dir, ignore_errors=True))


@lru_cache
def get_storage() -> LocalStorageAdapter:
    from app.config import get_settings

    return LocalStorageAdapter(storage_root=get_settings().storage_root)
