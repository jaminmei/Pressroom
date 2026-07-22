from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.test_set_storage import TestSetStorageAdapter
from app.storage.utils import ensure_path_within_root


def test_ensure_path_within_root_accepts_nested_path(tmp_path: Path) -> None:
    root = (tmp_path / "storage" / "test_sets").resolve()
    nested = root / "ts_001" / "documents" / "doc_001_invoice.pdf"

    resolved = ensure_path_within_root(nested, root)

    assert resolved == nested.resolve()


def test_ensure_path_within_root_rejects_traversal(tmp_path: Path) -> None:
    root = (tmp_path / "storage" / "test_sets").resolve()
    escaped = root.parent / "outside.txt"

    with pytest.raises(ValueError, match="Path traversal detected"):
        ensure_path_within_root(escaped, root)


@pytest.mark.asyncio
async def test_test_set_storage_save_read_delete_document(tmp_path: Path) -> None:
    storage = TestSetStorageAdapter(storage_root=tmp_path)
    content = b"evaluation fixture"

    storage_path = await storage.save_document(
        test_set_id="ts_eval_001",
        doc_id="doc_eval_001",
        filename="invoice sample.pdf",
        content=content,
    )

    assert storage_path.startswith("test_sets/ts_eval_001/documents/")
    assert Path(storage_path).name.startswith("doc_eval_001_")

    read_back = await storage.read_document(storage_path)
    assert read_back == content

    await storage.delete_document(storage_path)

    with pytest.raises(FileNotFoundError):
        await storage.read_document(storage_path)


@pytest.mark.asyncio
async def test_test_set_storage_delete_test_set_removes_namespace(tmp_path: Path) -> None:
    storage = TestSetStorageAdapter(storage_root=tmp_path)

    first_path = await storage.save_document(
        test_set_id="ts_eval_002",
        doc_id="doc_eval_001",
        filename="a.pdf",
        content=b"a",
    )
    second_path = await storage.save_document(
        test_set_id="ts_eval_002",
        doc_id="doc_eval_002",
        filename="b.png",
        content=b"b",
    )

    await storage.delete_test_set("ts_eval_002")

    with pytest.raises(FileNotFoundError):
        await storage.read_document(first_path)
    with pytest.raises(FileNotFoundError):
        await storage.read_document(second_path)
