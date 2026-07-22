from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services.image_preprocessor import ImagePreprocessor, ImageValidationError
from app.storage.local import LocalStorageAdapter


def _build_image_bytes(image_format: str, size: tuple[int, int] = (64, 32)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=image_format)
    return buffer.getvalue()


def _build_exif_rotated_jpeg() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (40, 20), color="white")
    exif = image.getexif()
    exif[274] = 6  # Rotate 90 degrees CW.
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_preprocess_png_success(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = ImagePreprocessor()

    source_path = await storage.save_file(
        "task_image_png", "original", "sample.png", _build_image_bytes("PNG")
    )
    result = await preprocessor.preprocess(
        task_id="task_image_png",
        file_path=source_path,
        mime_type="image/png",
        filename="sample.png",
        storage=storage,
    )

    assert result.data.format == "png"
    assert result.data.width == 64
    assert result.data.height == 32
    assert Path(result.data.file_path).name == "sample_preprocessed.png"
    assert await storage.file_exists(result.data.file_path)


@pytest.mark.asyncio
async def test_preprocess_rejects_invalid_image_bytes(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = ImagePreprocessor()
    source_path = await storage.save_file(
        "task_invalid_image", "original", "fake.png", b"not-an-image"
    )

    with pytest.raises(ImageValidationError, match="Invalid image format"):
        await preprocessor.preprocess(
            task_id="task_invalid_image",
            file_path=source_path,
            mime_type="image/png",
            filename="fake.png",
            storage=storage,
        )


@pytest.mark.asyncio
async def test_preprocess_rejects_oversized_dimensions(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = ImagePreprocessor()
    source_path = await storage.save_file(
        "task_oversized",
        "original",
        "large.png",
        _build_image_bytes("PNG", size=(10_001, 10)),
    )

    with pytest.raises(ImageValidationError, match="Image exceeds max dimensions 10000x10000"):
        await preprocessor.preprocess(
            task_id="task_oversized",
            file_path=source_path,
            mime_type="image/png",
            filename="large.png",
            storage=storage,
        )


@pytest.mark.asyncio
async def test_preprocess_applies_exif_rotation(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(storage_root=tmp_path)
    preprocessor = ImagePreprocessor()
    source_path = await storage.save_file(
        "task_exif_rotate",
        "original",
        "rotated.jpg",
        _build_exif_rotated_jpeg(),
    )

    result = await preprocessor.preprocess(
        task_id="task_exif_rotate",
        file_path=source_path,
        mime_type="image/jpeg",
        filename="rotated.jpg",
        storage=storage,
    )

    assert result.data.format == "jpeg"
    assert (result.data.width, result.data.height) == (20, 40)
