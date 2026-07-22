from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal, TypeAlias, cast

from PIL import Image, ImageOps, UnidentifiedImageError

from app.models.inputs import ImageData, ImageInput, ImageSource
from app.storage.base import StorageAdapter

ImageFormat: TypeAlias = Literal["png", "jpeg", "webp", "bmp", "tiff"]


class ImageValidationError(ValueError):
    """Raised when image input validation fails."""


class ImagePreprocessor:
    """Validate image uploads and build normalized ImageInput metadata."""

    MAX_DIMENSION = 10_000
    SUPPORTED_MIME_TYPES = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/tif",
    }

    _MIME_TO_FORMAT: dict[str, ImageFormat] = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
        "image/tif": "tiff",
    }

    _FORMAT_TO_EXTENSION: dict[ImageFormat, str] = {
        "png": "png",
        "jpeg": "jpg",
        "webp": "webp",
        "bmp": "bmp",
        "tiff": "tiff",
    }

    async def preprocess(
        self,
        *,
        task_id: str,
        file_path: str,
        mime_type: str,
        filename: str,
        storage: StorageAdapter,
    ) -> ImageInput:
        raw_bytes = await storage.read_file(file_path)
        processed_bytes, width, height, image_format = self._process_bytes(raw_bytes, mime_type)

        stem = Path(filename).stem or "image"
        extension = self._FORMAT_TO_EXTENSION[image_format]
        output_name = f"{stem}_preprocessed.{extension}"
        output_path = await storage.save_file(task_id, "preprocessed", output_name, processed_bytes)

        return ImageInput(
            source=ImageSource(
                type="upload",
                original_filename=filename,
                original_mime_type=mime_type,
            ),
            data=ImageData(
                file_path=output_path,
                width=width,
                height=height,
                format=image_format,
                size_bytes=len(processed_bytes),
            ),
        )

    def _process_bytes(
        self,
        raw_bytes: bytes,
        mime_type: str,
    ) -> tuple[bytes, int, int, ImageFormat]:
        if not raw_bytes:
            raise ImageValidationError("Image file is empty")

        normalized_mime = mime_type.lower()
        if normalized_mime not in self.SUPPORTED_MIME_TYPES:
            raise ImageValidationError(f"Unsupported image MIME type: {mime_type}")

        try:
            probe = BytesIO(raw_bytes)
            with Image.open(probe) as verifier:
                verifier.verify()

            source = BytesIO(raw_bytes)
            with Image.open(source) as image:
                corrected = ImageOps.exif_transpose(image)
                image_format = self._normalize_format(corrected.format or image.format)
                self._validate_mime_consistency(normalized_mime, image_format)

                width, height = corrected.size
                if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
                    raise ImageValidationError(
                        f"Image exceeds max dimensions {self.MAX_DIMENSION}x{self.MAX_DIMENSION}"
                    )

                output_buffer = BytesIO()
                save_image = corrected
                if image_format == "jpeg" and corrected.mode not in {"L", "RGB"}:
                    save_image = corrected.convert("RGB")
                save_image.save(output_buffer, format=image_format.upper())
        except ImageValidationError:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise ImageValidationError("Invalid image format") from exc

        return output_buffer.getvalue(), width, height, image_format

    def _normalize_format(self, image_format: str | None) -> ImageFormat:
        normalized = (image_format or "").lower()
        if normalized == "jpg":
            return "jpeg"
        if normalized in {"tif", "tiff"}:
            return "tiff"
        if normalized in {"png", "jpeg", "webp", "bmp"}:
            return cast(ImageFormat, normalized)
        raise ImageValidationError(f"Unsupported image format: {image_format}")

    def _validate_mime_consistency(self, mime_type: str, detected_format: ImageFormat) -> None:
        expected_format = self._MIME_TO_FORMAT.get(mime_type)
        if expected_format is None:
            raise ImageValidationError(f"Unsupported image MIME type: {mime_type}")
        if expected_format != detected_format:
            raise ImageValidationError("Image MIME type does not match file content")
