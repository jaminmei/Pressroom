"""Unit tests for magic_bytes pure functions."""

from __future__ import annotations

import pytest

from app.services.magic_bytes import MagicBytesError, detect_mime, validate_magic_bytes

# ── detect_mime ────────────────────────────────────────────────


def test_detect_mime_pdf():
    assert detect_mime(b"%PDF-1.4...") == "application/pdf"


def test_detect_mime_png():
    assert detect_mime(b"\x89PNG\r\n\x1a\n...") == "image/png"


def test_detect_mime_jpeg():
    assert detect_mime(b"\xff\xd8\xff\xe0...") == "image/jpeg"


def test_detect_mime_jp2():
    assert detect_mime(b"\xff\x4f\xff\x51...") == "image/jp2"


def test_detect_mime_tiff_little_endian():
    assert detect_mime(b"II*\x00...") == "image/tiff"


def test_detect_mime_tiff_big_endian():
    assert detect_mime(b"MM\x00*...") == "image/tiff"


def test_detect_mime_garbage_returns_none():
    assert detect_mime(b"garbage") is None


def test_detect_mime_empty_returns_none():
    assert detect_mime(b"") is None


# ── validate_magic_bytes ───────────────────────────────────────


def test_validate_valid_bytes_returns_none():
    assert validate_magic_bytes(b"%PDF-1.4...") is None


def test_validate_invalid_bytes_raises():
    with pytest.raises(MagicBytesError):
        validate_magic_bytes(b"garbage")


def test_validate_declared_mismatch_raises():
    with pytest.raises(MagicBytesError):
        validate_magic_bytes(b"%PDF-1.4...", declared_mime="image/png")


def test_validate_declared_match_returns_none():
    assert validate_magic_bytes(b"%PDF-1.4...", declared_mime="application/pdf") is None
