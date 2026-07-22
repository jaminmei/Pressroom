"""Shared constants for the API layer."""

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/tif",
        "text/plain",
        "text/html",
    }
)
