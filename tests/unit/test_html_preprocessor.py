from __future__ import annotations

from pathlib import Path

import pytest

from app.services.html_preprocessor import HtmlPreprocessor, HtmlValidationError
from app.storage.local import LocalStorageAdapter


@pytest.mark.asyncio
async def test_preprocess_html_utf8_success(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = HtmlPreprocessor()
    html = "<html><body><h1>Title</h1><p>內容</p></body></html>"
    source_path = await storage.save_file(
        "task_html_utf8",
        "original",
        "index.html",
        html.encode("utf-8"),
    )

    result = await preprocessor.preprocess(
        file_path=source_path,
        filename="index.html",
        storage=storage,
    )

    assert result.source.type == "html_extract"
    assert result.source.encoding == "utf-8"
    assert "<h1>Title</h1>" in result.content.raw
    assert result.content.char_count == len(result.content.raw)


@pytest.mark.asyncio
async def test_preprocess_html_big5_detection(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = HtmlPreprocessor()
    html = "<html><body><p>測試內容</p></body></html>"
    source_path = await storage.save_file(
        "task_html_big5",
        "original",
        "index.html",
        html.encode("big5"),
    )

    result = await preprocessor.preprocess(
        file_path=source_path,
        filename="index.html",
        storage=storage,
    )

    assert result.source.encoding in {"big5", "gbk", "gb2312"}
    assert "測試內容" in result.content.raw


@pytest.mark.asyncio
async def test_preprocess_html_removes_script_and_style(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = HtmlPreprocessor()
    html = """
    <html>
      <head><style>.hidden { display:none; }</style></head>
      <body>
        <script>alert('xss')</script>
        <p>Keep me</p>
      </body>
    </html>
    """
    source_path = await storage.save_file(
        "task_html_clean",
        "original",
        "index.html",
        html.encode("utf-8"),
    )

    result = await preprocessor.preprocess(
        file_path=source_path,
        filename="index.html",
        storage=storage,
    )

    assert "<script" not in result.content.raw.lower()
    assert "<style" not in result.content.raw.lower()
    assert "Keep me" in result.content.raw


@pytest.mark.asyncio
async def test_preprocess_html_rejects_oversized_file(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = HtmlPreprocessor()
    source_path = await storage.save_file(
        "task_html_large",
        "original",
        "large.html",
        b"x" * (HtmlPreprocessor.MAX_HTML_SIZE_BYTES + 1),
    )

    with pytest.raises(HtmlValidationError, match="HTML file exceeds max size"):
        await preprocessor.preprocess(
            file_path=source_path,
            filename="large.html",
            storage=storage,
        )
