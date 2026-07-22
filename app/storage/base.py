from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class StorageAdapter(ABC):
    """Storage abstraction for task-scoped file operations."""

    @abstractmethod
    async def save_file(self, task_id: str, category: str, filename: str, content: bytes) -> str:
        """Persist bytes and return the saved file path."""

    @abstractmethod
    async def save_stream(
        self,
        task_id: str,
        category: str,
        filename: str,
        stream: AsyncIterator[bytes],
    ) -> str:
        """Persist a chunk stream and return the saved file path.

        Used for streaming downloads where the full body is not known up-front
        and the caller wants to abort the write mid-stream when a byte ceiling
        is exceeded.
        """

    @abstractmethod
    async def read_file(self, file_path: str) -> bytes:
        """Read file content by path."""

    @abstractmethod
    async def delete_file(self, file_path: str) -> None:
        """Delete a single file by path."""

    @abstractmethod
    async def file_exists(self, file_path: str) -> bool:
        """Check whether a file exists."""

    @abstractmethod
    async def get_task_dir(self, task_id: str) -> str:
        """Return the task root directory path."""

    @abstractmethod
    async def delete_task(self, task_id: str) -> None:
        """Delete all task files for a task id."""
