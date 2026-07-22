"""Tests for text_processor utility module."""

from __future__ import annotations

import pytest

from app.utils.text_processor import clean_text, count_words, truncate

# --- clean_text tests ---


class TestCleanText:
    """Tests for clean_text function."""

    def test_empty_string(self) -> None:
        assert clean_text("") == ""

    def test_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="text must not be None"):
            clean_text(None)  # type: ignore[arg-type]

    def test_strip_leading_trailing_whitespace(self) -> None:
        assert clean_text("  hello  ") == "hello"

    def test_normalize_crlf_to_lf(self) -> None:
        assert clean_text("line1\r\nline2\r\nline3") == "line1\nline2\nline3"

    def test_normalize_cr_to_lf(self) -> None:
        assert clean_text("line1\rline2") == "line1\nline2"

    def test_collapse_multiple_spaces(self) -> None:
        assert clean_text("hello    world   foo") == "hello world foo"

    def test_remove_trailing_spaces_per_line(self) -> None:
        assert clean_text("line1   \nline2  ") == "line1\nline2"

    def test_combined_whitespace_normalization(self) -> None:
        input_text = "  hello   world  \r\n  foo   bar  \n  "
        expected = "hello world\n foo bar"
        assert clean_text(input_text) == expected

    def test_single_word(self) -> None:
        assert clean_text("  hello  ") == "hello"

    def test_only_whitespace(self) -> None:
        assert clean_text("   \n\n   ") == ""


# --- count_words tests ---


class TestCountWords:
    """Tests for count_words function."""

    def test_empty_string(self) -> None:
        result = count_words("")
        assert result == {"chars": 0, "words": 0, "lines": 0}

    def test_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="text must not be None"):
            count_words(None)  # type: ignore[arg-type]

    def test_single_word(self) -> None:
        result = count_words("hello")
        assert result == {"chars": 5, "words": 1, "lines": 1}

    def test_multiple_words(self) -> None:
        result = count_words("hello world foo")
        assert result == {"chars": 15, "words": 3, "lines": 1}

    def test_multiline(self) -> None:
        result = count_words("line one\nline two\nline three")
        assert result == {"chars": 28, "words": 6, "lines": 3}

    def test_single_line_with_newline(self) -> None:
        result = count_words("hello\n")
        assert result == {"chars": 6, "words": 1, "lines": 2}

    def test_multiple_spaces_between_words(self) -> None:
        result = count_words("hello    world")
        assert result == {"chars": 14, "words": 2, "lines": 1}

    def test_only_newlines(self) -> None:
        result = count_words("\n\n\n")
        assert result == {"chars": 3, "words": 0, "lines": 4}


# --- truncate tests ---


class TestTruncate:
    """Tests for truncate function."""

    def test_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="text must not be None"):
            truncate(None, 10)  # type: ignore[arg-type]

    def test_negative_max_length_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_length must be a positive integer"):
            truncate("hello", -1)

    def test_zero_max_length_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_length must be a positive integer"):
            truncate("hello", 0)

    def test_text_shorter_than_max_length(self) -> None:
        assert truncate("hello", 10) == "hello"

    def test_text_equal_to_max_length(self) -> None:
        assert truncate("hello", 5) == "hello"

    def test_text_longer_than_max_length(self) -> None:
        result = truncate("hello world", 8)
        assert result == "hello..."
        assert len(result) == 8

    def test_custom_suffix(self) -> None:
        result = truncate("hello world", 10, suffix="[...]")
        assert result == "hello[...]"
        assert len(result) == 10

    def test_suffix_longer_than_max_length(self) -> None:
        result = truncate("hello", 2, suffix="...")
        assert result == ".."
        assert len(result) == 2

    def test_suffix_equal_to_max_length(self) -> None:
        result = truncate("hello world", 3, suffix="...")
        assert result == "..."
        assert len(result) == 3

    def test_empty_string(self) -> None:
        assert truncate("", 5) == ""

    def test_does_not_mutate_input(self) -> None:
        original = "hello world"
        truncate(original, 5)
        assert original == "hello world"
