"""Path and filename utilities for document conversion pipeline."""

from __future__ import annotations

import os
import re


def get_extension(filename: str) -> str:
    """Extract file extension from a filename.

    Args:
        filename: Input filename (with or without path).

    Returns:
        Lowercase extension without the dot. Empty string if no extension.

    Raises:
        ValueError: If filename is None.
    """
    if filename is None:
        raise ValueError("filename must not be None")

    if not filename:
        return ""

    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()


def is_safe_path(path: str) -> bool:
    """Check if a path is safe from path traversal attacks.

    Args:
        path: File path to validate.

    Returns:
        True if the path contains no traversal sequences, False otherwise.

    Raises:
        ValueError: If path is None.
    """
    if path is None:
        raise ValueError("path must not be None")

    if not path:
        return True

    parts = path.replace("\\", "/").split("/")

    return ".." not in parts


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by keeping only safe characters.

    Preserves alphanumeric characters, hyphens, underscores, and dots.
    All other characters are replaced with underscores.

    Args:
        filename: Input filename to sanitize.

    Returns:
        Sanitized filename containing only safe characters.

    Raises:
        ValueError: If filename is None.
    """
    if filename is None:
        raise ValueError("filename must not be None")

    if not filename:
        return ""

    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)

    return sanitized
