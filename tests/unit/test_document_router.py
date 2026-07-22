from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services.document_router import DocumentRouter, UnsupportedMimeTypeError
from app.storage.local import LocalStorageAdapter


def _create_image_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 16), color="white").save(buffer, format=image_format)
    return buffer.getvalue()


def _patch_pdf_routing(
    monkeypatch: pytest.MonkeyPatch,
    fake_pages: list[Image.Image],
) -> None:
    """Patch _convert_pdf_page and _pdf_info so PDF tests work without pdf2image."""
    total = len(fake_pages)

    def _fake_convert(*args: object, **kwargs: object) -> list[Image.Image]:
        first_page = kwargs.get("first_page", 1)
        idx = int(first_page) - 1  # type: ignore[arg-type]
        if 0 <= idx < total:
            return [fake_pages[idx]]
        return []

    monkeypatch.setattr(
        "app.services.document_router._convert_pdf_page",
        _fake_convert,
    )
    monkeypatch.setattr(
        "app.services.document_router._pdf_info",
        lambda *a, **kw: {"Pages": total},
    )


@pytest.mark.asyncio
async def test_route_pdf_returns_correct_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")

    fake_pages = [
        Image.new("RGB", (100, 200)),
        Image.new("RGB", (100, 200)),
        Image.new("RGB", (100, 200)),
    ]

    _patch_pdf_routing(monkeypatch, fake_pages)

    outputs = await router.route(
        "task_pdf_count",
        str(pdf_path),
        "application/pdf",
        "sample.pdf",
    )

    assert len(outputs) == 3


@pytest.mark.asyncio
async def test_route_pdf_uses_page_naming_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")

    fake_pages = [Image.new("RGB", (90, 90)), Image.new("RGB", (90, 90))]
    _patch_pdf_routing(monkeypatch, fake_pages)

    outputs = await router.route(
        "task_pdf_naming",
        str(pdf_path),
        "application/pdf",
        "sample.pdf",
    )

    assert [Path(output.data.file_path).name for output in outputs] == [
        "page_001.png",
        "page_002.png",
    ]


@pytest.mark.asyncio
async def test_route_pdf_includes_page_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")

    fake_pages = [
        Image.new("RGB", (90, 90)),
        Image.new("RGB", (80, 70)),
        Image.new("RGB", (50, 40)),
    ]
    _patch_pdf_routing(monkeypatch, fake_pages)

    outputs = await router.route(
        "task_pdf_metadata",
        str(pdf_path),
        "application/pdf",
        "sample.pdf",
    )

    assert outputs[0].page_info.page_number == 1
    assert outputs[0].page_info.total_pages == 3
    assert outputs[2].page_info.page_number == 3
    assert outputs[2].page_info.total_pages == 3


@pytest.mark.asyncio
async def test_route_pdf_sets_pdf_convert_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")

    fake_pages = [Image.new("RGB", (120, 200))]
    _patch_pdf_routing(monkeypatch, fake_pages)

    outputs = await router.route(
        "task_pdf_source",
        str(pdf_path),
        "application/pdf",
        "sample.pdf",
    )

    assert outputs[0].source.type == "pdf_convert"
    assert outputs[0].source.conversion_path == ["pdf", "image"]


@pytest.mark.asyncio
async def test_route_image_png(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    router = DocumentRouter(storage=storage)

    file_path = await storage.save_file(
        "task_img_png",
        "original",
        "image.png",
        _create_image_bytes("PNG"),
    )

    outputs = await router.route("task_img_png", file_path, "image/png", "image.png")

    assert len(outputs) == 1
    assert outputs[0].data.format == "png"
    assert outputs[0].page_info is None


@pytest.mark.asyncio
async def test_route_image_jpeg(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    router = DocumentRouter(storage=storage)

    file_path = await storage.save_file(
        "task_img_jpeg",
        "original",
        "image.jpg",
        _create_image_bytes("JPEG"),
    )

    outputs = await router.route("task_img_jpeg", file_path, "image/jpeg", "image.jpg")

    assert len(outputs) == 1
    assert outputs[0].data.format == "jpeg"
    assert outputs[0].source.original_mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_route_text_plain(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    router = DocumentRouter(storage=storage)

    raw_text = "first line\nsecond line\n"
    file_path = await storage.save_file(
        "task_text", "original", "content.txt", raw_text.encode("utf-8")
    )

    outputs = await router.route("task_text", file_path, "text/plain", "content.txt")

    assert len(outputs) == 1
    assert outputs[0].content.raw == raw_text
    assert outputs[0].content.char_count == len(raw_text)
    assert outputs[0].content.line_count == 2


@pytest.mark.asyncio
async def test_route_text_html(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    router = DocumentRouter(storage=storage)

    raw_html = "<html><body><h1>Hello</h1><script>alert(1)</script></body></html>"
    file_path = await storage.save_file(
        "task_html",
        "original",
        "content.html",
        raw_html.encode("utf-8"),
    )

    outputs = await router.route("task_html", file_path, "text/html", "content.html")

    assert len(outputs) == 1
    assert outputs[0].source.type == "html_extract"
    assert "<script" not in outputs[0].content.raw.lower()
    assert "<h1>Hello</h1>" in outputs[0].content.raw


@pytest.mark.asyncio
async def test_route_unsupported_mime(tmp_path: Path) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))

    with pytest.raises(UnsupportedMimeTypeError):
        await router.route("task_bad", "some/path.bin", "application/zip", "archive.zip")


@pytest.mark.asyncio
async def test_route_pdf_converter_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = DocumentRouter(storage=LocalStorageAdapter(storage_root=tmp_path))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")

    def _raise_converter_error(*args: object, **kwargs: object) -> list[Image.Image]:
        raise RuntimeError("converter failed")

    monkeypatch.setattr("app.services.document_router._convert_pdf_page", _raise_converter_error)
    monkeypatch.setattr(
        "app.services.document_router._pdf_info",
        lambda *a, **kw: {"Pages": 1},
    )

    with pytest.raises(RuntimeError, match="converter failed"):
        await router.route("task_pdf_fail", str(pdf_path), "application/pdf", "sample.pdf")
