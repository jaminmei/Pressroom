"""Magic-byte signature validation for uploaded file content.

Pure functions — no I/O, no async, no external libraries.
Validates the first 8 bytes of a file against known signatures.
"""

from __future__ import annotations


class MagicBytesError(ValueError):
    """Raised when file content fails magic-byte validation."""


# Single signatures use bytes; formats with multiple signatures use a list.
ALLOWED_SIGNATURES: dict[str, bytes | list[bytes]] = {
    "application/pdf": b"%PDF",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/jp2": b"\xff\x4f\xff\x51",
    "image/tiff": [b"II*\x00", b"MM\x00*"],
}


def detect_mime(head: bytes) -> str | None:
    """Return the MIME type matching *head*, or None if no signature matches."""
    for mime, sig in ALLOWED_SIGNATURES.items():
        if isinstance(sig, list):
            if any(head.startswith(s) for s in sig):
                return mime
        elif head.startswith(sig):
            return mime
    return None


def validate_magic_bytes(
    head: bytes,
    declared_mime: str | None = None,
) -> None:
    """Validate *head* against allowed signatures.

    Raises MagicBytesError if:
    - *head* matches no allowed signature, or
    - *declared_mime* is set and does not match the detected MIME type.
    Returns None on success.
    """
    detected = detect_mime(head)
    if detected is None:
        raise MagicBytesError("File content does not match any allowed type")
    if declared_mime is not None and declared_mime != detected:
        raise MagicBytesError(
            f"Declared MIME type {declared_mime!r} does not match detected type {detected!r}"
        )
