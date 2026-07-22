"""Unit tests for UploadHandler.receive_upload with mocked storage."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.services.upload_handler import UploadHandler, UploadHandlerError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockUploadFile:
    """Minimal async UploadFile stub — only the surface UploadHandler touches."""

    def __init__(
        self,
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
        size: int | None = None,
    ) -> None:
        self.filename = filename
        self._content = content
        self.content_type = content_type
        self.size = size if size is not None else len(content)
        self._cursor = 0

    async def read(self, size: int = -1) -> bytes:
        if self._cursor >= len(self._content):
            return b""
        end = self._cursor + max(size, 1)
        chunk = self._content[self._cursor : end]
        self._cursor += len(chunk)
        return chunk


def _build_handler(
    *,
    read_content: bytes,
    max_bytes: int = 20971520,
) -> tuple[UploadHandler, MagicMock]:
    """Return a handler wired to a fully-mocked LocalStorageAdapter.

    *read_content* is what ``storage.read_file`` will return.
    """
    settings = Settings(input_upload_max_bytes=max_bytes)
    storage = MagicMock()
    storage.get_task_dir = AsyncMock(return_value="/storage/tasks")
    storage.file_exists = AsyncMock(return_value=True)
    storage.delete_file = AsyncMock()
    storage.read_file = AsyncMock(return_value=read_content)

    # save_stream mock MUST consume the async generator so that the
    # bounded_chunks generator embedded in the handler actually runs
    # (otherwise size-limit and empty-content behaviour is invisible).
    async def _streaming_save(task_id, category, filename, stream):
        async for _chunk in stream:
            pass
        return f"/storage/tasks/{task_id}/{category}/{filename}"

    storage.save_stream = AsyncMock(side_effect=_streaming_save)

    handler = UploadHandler(settings=settings, storage=storage)
    return handler, storage


# ---------------------------------------------------------------------------
# 1. Happy path — valid PDF
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_happy_path_pdf() -> None:
    """Valid PDF magic bytes + valid filename → save_stream called once, path returned."""
    pdf_content = b"%PDF-1.4\n%some pdf content here"
    file_part = _MockUploadFile(
        filename="invoice.pdf",
        content=pdf_content,
        content_type="application/pdf",
    )
    handler, storage = _build_handler(read_content=pdf_content)

    result = await handler.receive_upload(file_part, "r1")  # type: ignore[arg-type]

    assert result == "/storage/tasks/r1/original/invoice.pdf"
    # save_stream called once, correct positional args, generator is ANY
    storage.save_stream.assert_called_once_with("r1", "original", "invoice.pdf", ANY)
    # read_file was called to validate magic bytes
    storage.read_file.assert_called_once_with("/storage/tasks/r1/original/invoice.pdf")
    # no cleanup triggered
    storage.delete_file.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Magic byte mismatch — declared PDF, actual HTML
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_magic_byte_mismatch() -> None:
    """HTML body declared as PDF → UploadHandlerError, cleanup runs."""
    html = b"<html><body>not a pdf</body></html>"
    file_part = _MockUploadFile(
        filename="evil.html",
        content=html,
        content_type="application/pdf",  # lying
    )
    handler, storage = _build_handler(read_content=html)

    with pytest.raises(UploadHandlerError, match="does not match"):
        await handler.receive_upload(file_part, "r2")  # type: ignore[arg-type]

    # save_stream WAS called (file was written before validation)
    storage.save_stream.assert_called_once()
    # cleanup ran
    storage.delete_file.assert_called_once()
    storage.file_exists.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Size cap exceeded — layer-2 stream abort + cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_size_cap_exceeded() -> None:
    """Content over configured limit → UploadHandlerError, cleanup runs."""
    oversize = b"x" * 200  # exceeds the 100-byte cap below
    file_part = _MockUploadFile(
        filename="big.pdf",
        content=oversize,
        content_type="application/pdf",
        size=50,  # under the 100-byte cap → layer-1 passes, layer-2 catches
    )
    handler, storage = _build_handler(read_content=oversize, max_bytes=100)

    with pytest.raises(UploadHandlerError, match="exceeds limit"):
        await handler.receive_upload(file_part, "r3")  # type: ignore[arg-type]

    # save_stream was attempted but bounded_chunks raised mid-stream
    storage.save_stream.assert_called_once_with("r3", "original", "big.pdf", ANY)
    # cleanup should have run
    storage.delete_file.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Path traversal filename — sanitized, no slash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_path_traversal_filename_sanitized() -> None:
    """'../../../etc/passwd' → sanitized to safe form, written under expected dir."""
    pdf = b"%PDF-1.4 content"
    file_part = _MockUploadFile(
        filename="../../../etc/passwd",
        content=pdf,
        content_type="application/pdf",
        size=len(pdf),
    )
    handler, storage = _build_handler(read_content=pdf)

    result = await handler.receive_upload(file_part, "r4")  # type: ignore[arg-type]

    # extract the sanitized filename that was passed to save_stream
    save_call = storage.save_stream.call_args
    sanitized = save_call[0][2]  # 3rd positional arg = filename
    assert "/" not in sanitized, f"unsanitized filename: {sanitized!r}"
    assert ".." not in sanitized.split("/"), f"traversal chars in filename: {sanitized!r}"
    # sanitize_filename keeps alnum . _ - so . stays; but since / → _,
    # the path traversal is neutralised.
    assert result.startswith("/storage/tasks/r4/original/")


# ---------------------------------------------------------------------------
# 5. Shell metachar filename — sanitized, no shell-significant chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_shell_metachar_filename_sanitized() -> None:
    """'$(rm -rf /).pdf' → sanitized, no $ ( ) backticks or /."""
    pdf = b"%PDF-1.4 content"
    file_part = _MockUploadFile(
        filename="$(rm -rf /).pdf",
        content=pdf,
        content_type="application/pdf",
        size=len(pdf),
    )
    handler, storage = _build_handler(read_content=pdf)

    result = await handler.receive_upload(file_part, "r5")  # type: ignore[arg-type]

    save_call = storage.save_stream.call_args
    sanitized = save_call[0][2]
    for ch in ("$", "(", ")", "`", "/"):
        assert ch not in sanitized, f"shell char {ch!r} survived in {sanitized!r}"
    assert result.startswith("/storage/tasks/r5/original/")


# ---------------------------------------------------------------------------
# 6. Unicode filename — sanitized per regex [^a-zA-Z0-9._-] → _
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_unicode_filename_sanitized() -> None:
    """'café.pdf' → 'caf_.pdf' (é is outside the safe character class)."""
    pdf = b"%PDF-1.4 content"
    file_part = _MockUploadFile(
        filename="café.pdf",
        content=pdf,
        content_type="application/pdf",
        size=len(pdf),
    )
    handler, storage = _build_handler(read_content=pdf)

    result = await handler.receive_upload(file_part, "r6")  # type: ignore[arg-type]

    save_call = storage.save_stream.call_args
    assert save_call[0][2] == "caf_.pdf", f"expected 'caf_.pdf', got {save_call[0][2]!r}"
    assert result == "/storage/tasks/r6/original/caf_.pdf"


# ---------------------------------------------------------------------------
# 7. Empty content → magic-byte failure on zero-length head
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_empty_content() -> None:
    """Zero-byte file → validate_magic_bytes fails on empty head → UploadHandlerError."""
    file_part = _MockUploadFile(
        filename="empty.bin",
        content=b"",  # no data
        content_type="application/pdf",
        size=0,
    )
    handler, storage = _build_handler(read_content=b"")

    with pytest.raises(UploadHandlerError, match="does not match any allowed"):
        await handler.receive_upload(file_part, "r7")  # type: ignore[arg-type]

    # save_stream still called (opened empty file, generator never yielded)
    storage.save_stream.assert_called_once()
    # cleanup ran because magic-byte validation failed
    storage.delete_file.assert_called_once()
