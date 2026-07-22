from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """Normalize common OCR/text whitespace without changing line structure."""
    if text is None:
        raise ValueError("text must not be None")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line.rstrip()) for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def count_words(text: str) -> dict[str, int]:
    """Return character, word, and line counts for text."""
    if text is None:
        raise ValueError("text must not be None")

    return {
        "chars": len(text),
        "words": len(re.findall(r"\S+", text)),
        "lines": 0 if text == "" else text.count("\n") + 1,
    }


def truncate(text: str, max_length: int, *, suffix: str = "...") -> str:
    """Truncate text to max_length, reserving room for suffix when needed."""
    if text is None:
        raise ValueError("text must not be None")
    if max_length <= 0:
        raise ValueError("max_length must be a positive integer")
    if len(text) <= max_length:
        return text
    if len(suffix) >= max_length:
        return suffix[:max_length]
    return f"{text[: max_length - len(suffix)]}{suffix}"
