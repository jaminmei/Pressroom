from __future__ import annotations

import asyncio
from functools import partial
from io import BytesIO
from typing import Any, Callable, cast

from PIL import Image

from app.models.inputs import (
    ImageData,
    ImageInput,
    ImageSource,
    PageInfo,
    TextContent,
    TextInput,
    TextSource,
)
from app.services.html_preprocessor import HtmlPreprocessor
from app.services.image_preprocessor import ImagePreprocessor
from app.storage.base import StorageAdapter


def _convert_pdf_page(*args: object, **kwargs: object) -> list[Image.Image]:
    try:
        from pdf2image import convert_from_path as convert_impl
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("pdf2image is required for PDF routing") from exc
    convert_any = cast(Callable[..., list[Image.Image]], convert_impl)
    return convert_any(*args, **kwargs)


def _pdf_info(*args: object, **kwargs: object) -> dict[str, object]:
    try:
        from pdf2image import pdfinfo_from_path as pdfinfo_impl
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("pdf2image is required for PDF routing") from exc
    info_func = cast(Callable[..., object], pdfinfo_impl)
    info: Any = info_func(*args, **kwargs)
    if isinstance(info, dict):
        return info
    raise RuntimeError("pdfinfo_from_path returned non-dict metadata")


class UnsupportedMimeTypeError(ValueError):
    """Raised when a MIME type is not handled by the document router."""


class DocumentRouter:
    """Route uploaded documents into ImageInput or TextInput structures."""

    PDF_MIME = "application/pdf"
    IMAGE_MIMES = ImagePreprocessor.SUPPORTED_MIME_TYPES
    TEXT_MIME = "text/plain"
    HTML_MIME = "text/html"

    def __init__(
        self,
        storage: StorageAdapter,
        *,
        image_preprocessor: ImagePreprocessor | None = None,
        html_preprocessor: HtmlPreprocessor | None = None,
    ) -> None:
        self.storage = storage
        self.image_preprocessor = image_preprocessor or ImagePreprocessor()
        self.html_preprocessor = html_preprocessor or HtmlPreprocessor()

    async def route(
        self, task_id: str, file_path: str, mime_type: str, filename: str
    ) -> list[ImageInput] | list[TextInput]:
        normalized_mime = mime_type.lower()

        if normalized_mime == self.PDF_MIME:
            return await self._convert_pdf_to_images(
                task_id=task_id,
                pdf_path=file_path,
                filename=filename,
            )
        if normalized_mime in self.IMAGE_MIMES:
            return [
                await self.image_preprocessor.preprocess(
                    task_id=task_id,
                    file_path=file_path,
                    mime_type=normalized_mime,
                    filename=filename,
                    storage=self.storage,
                )
            ]
        if normalized_mime == self.HTML_MIME:
            return [
                await self.html_preprocessor.preprocess(
                    file_path=file_path,
                    filename=filename,
                    storage=self.storage,
                )
            ]
        if normalized_mime == self.TEXT_MIME:
            return [await self._create_text_input(file_path=file_path, filename=filename)]

        raise UnsupportedMimeTypeError(f"Unsupported MIME type: {mime_type}")

    async def _convert_pdf_to_images(
        self, task_id: str, pdf_path: str, filename: str, dpi: int = 300
    ) -> list[ImageInput]:
        loop = asyncio.get_running_loop()

        # Get total page count without loading all pages into memory.
        pdf_info = await loop.run_in_executor(None, _pdf_info, pdf_path)
        pages_value = pdf_info.get("Pages", 0)
        if isinstance(pages_value, int):
            total_pages = pages_value
        elif isinstance(pages_value, str):
            total_pages = int(pages_value)
        else:
            total_pages = 0
        if total_pages == 0:
            return []

        outputs: list[ImageInput] = []

        for page_index in range(1, total_pages + 1):
            # Convert one page at a time to avoid loading all pages into memory.
            convert_page = partial(
                _convert_pdf_page,
                pdf_path,
                dpi=dpi,
                first_page=page_index,
                last_page=page_index,
            )
            single_page_images: list[Image.Image] = await loop.run_in_executor(None, convert_page)
            if not single_page_images:
                continue
            page_image = single_page_images[0]

            output_name = f"page_{page_index:03d}.png"
            image_buffer = BytesIO()
            page_image.save(image_buffer, format="PNG")
            image_bytes = image_buffer.getvalue()
            saved_path = await self.storage.save_file(task_id, "images", output_name, image_bytes)
            width, height = page_image.size

            outputs.append(
                ImageInput(
                    source=ImageSource(
                        type="pdf_convert",
                        original_filename=filename,
                        original_mime_type=self.PDF_MIME,
                        conversion_path=["pdf", "image"],
                    ),
                    data=ImageData(
                        file_path=saved_path,
                        width=width,
                        height=height,
                        format="png",
                        size_bytes=len(image_bytes),
                    ),
                    page_info=PageInfo(page_number=page_index, total_pages=total_pages),
                )
            )

        return outputs

    async def _create_text_input(self, file_path: str, filename: str) -> TextInput:
        raw_bytes = await self.storage.read_file(file_path)
        raw_text = raw_bytes.decode("utf-8", errors="replace")

        return TextInput(
            source=TextSource(
                type="plain_text",
                original_filename=filename,
                original_mime_type=self.TEXT_MIME,
                encoding="utf-8",
            ),
            content=TextContent(
                raw=raw_text,
                char_count=len(raw_text),
                line_count=len(raw_text.splitlines()),
            ),
        )
