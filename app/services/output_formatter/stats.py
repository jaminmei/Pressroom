from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def count_visible_chars(text: str) -> int:
    """Count visible characters by removing all whitespace."""
    return len("".join(text.split()))


def count_words(text: str) -> int:
    """Count words with CJK-by-character and latin-number token rules."""
    cjk_chars = len(_CJK_CHAR_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    return cjk_chars + words


def weighted_confidence(confidence_chars: Iterable[tuple[float, int]]) -> float | None:
    """Compute char-weighted confidence and round to 2 decimals."""
    weighted_sum = 0.0
    total_chars = 0

    for confidence, char_count in confidence_chars:
        if char_count <= 0:
            continue
        weighted_sum += float(confidence) * char_count
        total_chars += char_count

    if total_chars == 0:
        return None

    value = Decimal(str(weighted_sum / total_chars))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def collect_block_stats(
    block: Mapping[str, Any],
    visible_text: str,
) -> tuple[int, int, tuple[float, int] | None]:
    """Collect char/word and weighted-confidence pair for a block."""
    if bool(block.get("is_continuation")):
        return 0, 0, None

    if not visible_text:
        return 0, 0, None

    char_count = count_visible_chars(visible_text)
    word_count = count_words(visible_text)

    confidence = block.get("confidence")
    confidence_pair: tuple[float, int] | None = None
    if isinstance(confidence, (int, float)) and char_count > 0:
        confidence_pair = (float(confidence), char_count)

    return char_count, word_count, confidence_pair
