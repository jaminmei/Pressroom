from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.services import document_thumbnail
from app.services.document_thumbnail import (
    UnsupportedThumbnailMimeTypeError,
    generate_document_thumbnail,
)


def _image_bytes(*, image_format: str = "PNG", size: tuple[int, int] = (800, 400)) -> bytes:
    image = Image.new("RGB", size, "navy")
    output = BytesIO()
    image.save(output, format=image_format)
    image.close()
    return output.getvalue()


def test_image_thumbnail_is_bounded_webp_without_source_dimensions() -> None:
    thumbnail = generate_document_thumbnail(_image_bytes(), "image/png", 96)

    with Image.open(BytesIO(thumbnail)) as image:
        assert image.format == "WEBP"
        assert image.size == (96, 48)
        assert image.getexif() == {}


def test_pdf_thumbnail_uses_first_rendered_page(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered_page = Image.new("RGB", (600, 900), "white")
    monkeypatch.setattr(
        document_thumbnail,
        "_convert_pdf_first_page",
        lambda _content: rendered_page.copy(),
    )

    thumbnail = generate_document_thumbnail(b"%PDF", "application/pdf", 640)

    with Image.open(BytesIO(thumbnail)) as image:
        assert image.format == "WEBP"
        assert image.size == (427, 640)
    rendered_page.close()


def test_unsupported_mime_type_is_rejected() -> None:
    with pytest.raises(UnsupportedThumbnailMimeTypeError):
        generate_document_thumbnail(b"plain text", "text/plain", 96)
