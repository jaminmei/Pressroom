from pathlib import Path

import pytest

from app.storage.local import LocalStorageAdapter


@pytest.mark.asyncio
async def test_save_and_read_file(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(storage_root=tmp_path)

    file_path = await adapter.save_file("task_1", "original", "doc.pdf", b"pdf-bytes")

    assert file_path == str(tmp_path / "tasks" / "task_1" / "original" / "doc.pdf")
    assert await adapter.read_file(file_path) == b"pdf-bytes"


@pytest.mark.asyncio
async def test_file_exists(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(storage_root=tmp_path)

    file_path = await adapter.save_file("task_2", "images", "page_001.png", b"img")

    assert await adapter.file_exists(file_path) is True
    missing_file = tmp_path / "tasks" / "task_2" / "images" / "missing.png"
    assert await adapter.file_exists(str(missing_file)) is False


@pytest.mark.asyncio
async def test_delete_file(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(storage_root=tmp_path)

    file_path = await adapter.save_file("task_3", "intermediate", "ocr_result.json", b"{}")
    await adapter.delete_file(file_path)

    assert await adapter.file_exists(file_path) is False


@pytest.mark.asyncio
async def test_delete_task(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(storage_root=tmp_path)

    await adapter.save_file("task_4", "original", "doc.pdf", b"pdf")
    await adapter.save_file("task_4", "output", "doc.md", b"markdown")

    task_dir = Path(await adapter.get_task_dir("task_4"))
    assert task_dir.exists()

    await adapter.delete_task("task_4")

    assert task_dir.exists() is False


@pytest.mark.asyncio
async def test_save_creates_directories(tmp_path: Path) -> None:
    adapter = LocalStorageAdapter(storage_root=tmp_path)

    target_dir = tmp_path / "tasks" / "task_5" / "images"
    assert target_dir.exists() is False

    file_path = await adapter.save_file("task_5", "images", "page_001.png", b"img")

    assert target_dir.exists() is True
    assert Path(file_path).exists() is True
