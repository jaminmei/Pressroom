"""Tests for path_utils module."""

from __future__ import annotations

import pytest

from app.utils.path_utils import get_extension, is_safe_path, sanitize_filename

# --- get_extension ---


class TestGetExtension:
    """Tests for get_extension function."""

    def test_simple_extension(self) -> None:
        assert get_extension("document.pdf") == "pdf"

    def test_uppercase_extension(self) -> None:
        assert get_extension("image.PNG") == "png"

    def test_mixed_case_extension(self) -> None:
        assert get_extension("archive.Zip") == "zip"

    def test_double_extension(self) -> None:
        assert get_extension("archive.tar.gz") == "gz"

    def test_no_extension(self) -> None:
        assert get_extension("README") == ""

    def test_hidden_file(self) -> None:
        # os.path.splitext treats dotfiles as having no extension
        assert get_extension(".gitignore") == ""

    def test_empty_string(self) -> None:
        assert get_extension("") == ""

    def test_only_dot(self) -> None:
        assert get_extension(".") == ""

    def test_multiple_dots(self) -> None:
        assert get_extension("file.name.with.dots.txt") == "txt"

    def test_path_with_extension(self) -> None:
        assert get_extension("/some/path/to/file.jpg") == "jpg"

    def test_windows_path(self) -> None:
        assert get_extension("C:\\Users\\doc\\file.docx") == "docx"

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="filename must not be None"):
            get_extension(None)  # type: ignore[arg-type]


# --- is_safe_path ---


class TestIsSafePath:
    """Tests for is_safe_path function."""

    def test_simple_filename(self) -> None:
        assert is_safe_path("document.pdf") is True

    def test_normal_path(self) -> None:
        assert is_safe_path("uploads/documents/report.pdf") is True

    def test_traversal_attack(self) -> None:
        assert is_safe_path("../etc/passwd") is False

    def test_traversal_in_middle(self) -> None:
        assert is_safe_path("uploads/../etc/passwd") is False

    def test_traversal_at_end(self) -> None:
        assert is_safe_path("uploads/..") is False

    def test_double_traversal(self) -> None:
        assert is_safe_path("../../etc/passwd") is False

    def test_empty_string(self) -> None:
        assert is_safe_path("") is True

    def test_current_dir(self) -> None:
        assert is_safe_path("./file.txt") is True

    def test_absolute_path_safe(self) -> None:
        assert is_safe_path("/var/data/files/document.pdf") is True

    def test_encoded_traversal(self) -> None:
        # os.path.normpath resolves .. components regardless
        assert is_safe_path("uploads/..%2Fetc") is True  # not actual traversal after normpath

    def test_backslash_traversal(self) -> None:
        assert is_safe_path("..\\windows\\system32") is False

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="path must not be None"):
            is_safe_path(None)  # type: ignore[arg-type]


# --- sanitize_filename ---


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_clean_filename(self) -> None:
        assert sanitize_filename("document.pdf") == "document.pdf"

    def test_spaces_replaced(self) -> None:
        assert sanitize_filename("my file name.txt") == "my_file_name.txt"

    def test_special_chars_replaced(self) -> None:
        assert sanitize_filename("file@#$%.doc") == "file____.doc"

    def test_chinese_chars_replaced(self) -> None:
        # Each non-ASCII char becomes one underscore
        assert sanitize_filename("文件名.pdf") == "___.pdf"

    def test_only_safe_chars(self) -> None:
        assert sanitize_filename("hello-world_v1.2.txt") == "hello-world_v1.2.txt"

    def test_empty_string(self) -> None:
        assert sanitize_filename("") == ""

    def test_all_special_chars(self) -> None:
        result = sanitize_filename("!@#$%^&*()")
        assert all(c == "_" for c in result)

    def test_hyphen_preserved(self) -> None:
        assert sanitize_filename("my-file") == "my-file"

    def test_underscore_preserved(self) -> None:
        assert sanitize_filename("my_file") == "my_file"

    def test_dot_preserved(self) -> None:
        assert sanitize_filename("file.name") == "file.name"

    def test_numbers_preserved(self) -> None:
        assert sanitize_filename("file123") == "file123"

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="filename must not be None"):
            sanitize_filename(None)  # type: ignore[arg-type]
