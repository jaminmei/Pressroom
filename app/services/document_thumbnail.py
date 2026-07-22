from __future__ import annotations

from io import BytesIO
from typing import Callable, cast

from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
PDF_MIME_TYPE = "application/pdf"


class UnsupportedThumbnailMimeTypeError(ValueError):
    """Raised when thumbnail generation does not support a document MIME type."""


class ThumbnailGenerationError(ValueError):
    """Raised when a supported document cannot be decoded or rendered."""


def _convert_pdf_first_page(content: bytes) -> Image.Image:
    try:
        from pdf2image import convert_from_bytes as convert_impl
    except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise ThumbnailGenerationError("PDF thumbnail support is unavailable") from exc

    convert = cast(Callable[..., list[Image.Image]], convert_impl)
    pages = convert(
        content,
        dpi=96,
        first_page=1,
        last_page=1,
        fmt="ppm",
        thread_count=1,
    )
    if not pages:
        raise ThumbnailGenerationError("PDF does not contain a renderable first page")
    return pages[0]


def _load_source_image(content: bytes, mime_type: str) -> Image.Image:
    if mime_type == PDF_MIME_TYPE:
        return _convert_pdf_first_page(content)
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise UnsupportedThumbnailMimeTypeError(f"Unsupported thumbnail MIME type: {mime_type}")

    image = Image.open(BytesIO(content))
    image.seek(0)
    image.load()
    return image


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    oriented = ImageOps.exif_transpose(image)
    if "A" not in oriented.getbands():
        return oriented.convert("RGB")

    rgba = oriented.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def generate_document_thumbnail(content: bytes, mime_type: str, size: int) -> bytes:
    """Render a document thumbnail as metadata-free WebP bounded by ``size`` pixels."""

    if size not in {96, 640}:
        raise ValueError(f"Unsupported thumbnail size: {size}")

    source: Image.Image | None = None
    rendered: Image.Image | None = None
    try:
        source = _load_source_image(content, mime_type.lower())
        rendered = _flatten_to_rgb(source)
        rendered.thumbnail((size, size), Image.Resampling.LANCZOS)

        output = BytesIO()
        rendered.save(output, format="WEBP", quality=82, method=4)
        return output.getvalue()
    except UnsupportedThumbnailMimeTypeError:
        raise
    except ThumbnailGenerationError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise ThumbnailGenerationError("Document could not be rendered as a thumbnail") from exc
    except Exception as exc:  # PDF renderers expose backend-specific exception types.
        raise ThumbnailGenerationError("Document could not be rendered as a thumbnail") from exc
    finally:
        if rendered is not None and rendered is not source:
            rendered.close()
        if source is not None:
            source.close()
