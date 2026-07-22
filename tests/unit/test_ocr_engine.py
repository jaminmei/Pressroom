"""Unit tests for OCR Engine and DocTags Converter."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import helpers — load engine modules without polluting sys.path
# ---------------------------------------------------------------------------

_ENGINE_ROOT = Path(__file__).resolve().parents[2] / "engines" / "ocr"


def _load_module(name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Mock rapidocr_onnxruntime before importing OCREngine
_mock_rapid = MagicMock()
sys.modules.setdefault("rapidocr_onnxruntime", _mock_rapid)

_converter_mod = _load_module(
    "ocr_doctags_converter", _ENGINE_ROOT / "src" / "doctags_converter.py"
)
_engine_mod = _load_module("ocr_engine_mod", _ENGINE_ROOT / "src" / "ocr_engine.py")

DocTagsConverter = _converter_mod.DocTagsConverter
OCREngine = _engine_mod.OCREngine


# ---------------------------------------------------------------------------
# DocTagsConverter tests
# ---------------------------------------------------------------------------


class TestDocTagsConverterEmptyInput:
    """Test DocTags converter with empty OCR results."""

    def test_empty_list_returns_empty_children(self) -> None:
        converter = DocTagsConverter()
        result = converter.convert(ocr_result=[])

        assert result["content"]["type"] == "doc"
        assert result["content"]["children"] == []

    def test_empty_list_statistics_are_zero(self) -> None:
        converter = DocTagsConverter()
        result = converter.convert(ocr_result=[])
        stats = result["meta"]["statistics"]

        assert stats["char_count"] == 0
        assert stats["word_count"] == 0
        assert stats["block_count"] == 0


class TestDocTagsConverterSingleLine:
    """Test DocTags converter with a single text line."""

    def test_single_line_produces_one_block(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Hello World", 0.95)],
        ]
        result = converter.convert(ocr_result)

        children = result["content"]["children"]
        assert len(children) == 1
        assert children[0]["text"] == "Hello World"
        assert children[0]["type"] == "paragraph"
        assert children[0]["confidence"] == pytest.approx(0.95)

    def test_single_line_has_bbox(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[10, 20], [110, 20], [110, 40], [10, 40]], ("text", 0.9)],
        ]
        result = converter.convert(ocr_result)
        bbox = result["content"]["children"][0]["bbox"]

        assert bbox["x"] == 10
        assert bbox["y"] == 20
        assert bbox["width"] == 100
        assert bbox["height"] == 20


class TestDocTagsConverterMultiLine:
    """Test DocTags converter with multiple text lines."""

    def test_multiple_lines_produce_multiple_blocks(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Line 1", 0.9)],
            [[[0, 30], [100, 30], [100, 50], [0, 50]], ("Line 2", 0.85)],
            [[[0, 60], [100, 60], [100, 80], [0, 80]], ("Line 3", 0.92)],
        ]
        result = converter.convert(ocr_result)

        children = result["content"]["children"]
        assert len(children) == 3
        assert [c["text"] for c in children] == ["Line 1", "Line 2", "Line 3"]

    def test_statistics_aggregate_correctly(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Hello World", 0.9)],
            [[[0, 30], [100, 30], [100, 50], [0, 50]], ("Foo", 0.85)],
        ]
        result = converter.convert(ocr_result)
        stats = result["meta"]["statistics"]

        assert stats["char_count"] == len("Hello World") + len("Foo")
        assert stats["word_count"] == 3  # "Hello", "World", "Foo"
        assert stats["block_count"] == 2


class TestDocTagsConverterMalformedInput:
    """Test DocTags converter with malformed OCR results."""

    def test_skips_line_with_wrong_tuple_length(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("text",)],
            [[[0, 30], [100, 30], [100, 50], [0, 50]], ("valid", 0.9)],
        ]
        result = converter.convert(ocr_result)
        assert len(result["content"]["children"]) == 1
        assert result["content"]["children"][0]["text"] == "valid"

    def test_skips_line_with_wrong_outer_length(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            ["only_one_element"],
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("ok", 0.8)],
        ]
        result = converter.convert(ocr_result)
        assert len(result["content"]["children"]) == 1

    def test_malformed_line_content_is_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        sentinel = "PRIVATE-OCR-LINE-SENTINEL"
        caplog.set_level("WARNING", logger="ocr_doctags_converter")

        DocTagsConverter().convert([[sentinel]])

        assert sentinel not in caplog.text


class TestDocTagsConverterPageNumber:
    """Test DocTags converter page number handling."""

    def test_page_number_added_to_blocks(self) -> None:
        converter = DocTagsConverter()
        ocr_result = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Page text", 0.9)],
        ]
        result = converter.convert(ocr_result, page_number=3)

        assert result["content"]["children"][0]["page_number"] == 3
        assert result["pages"] == [{"number": 3}]

    def test_no_page_number_omits_pages_key(self) -> None:
        converter = DocTagsConverter()
        result = converter.convert(ocr_result=[], page_number=None)
        assert "pages" not in result


class TestDocTagsConverterSourceInfo:
    """Test DocTags converter source info building."""

    def test_source_info_with_no_path(self) -> None:
        converter = DocTagsConverter()
        result = converter.convert(ocr_result=[], source_path=None)
        source = result["meta"]["source"]

        assert source["filename"] == "unknown"
        assert source["mime_type"] == "image/png"

    def test_source_info_with_nonexistent_path(self) -> None:
        converter = DocTagsConverter()
        result = converter.convert(ocr_result=[], source_path="/tmp/nonexistent_ocr_test.jpg")
        source = result["meta"]["source"]

        assert source["filename"] == "nonexistent_ocr_test.jpg"


class TestDocTagsConverterMergePages:
    """Test DocTags converter merge_page_doctags."""

    def test_merge_empty_list(self) -> None:
        converter = DocTagsConverter()
        result = converter.merge_page_doctags([])

        assert result["content"]["children"] == []
        assert result["pages"] == []

    def test_merge_two_pages(self) -> None:
        converter = DocTagsConverter()
        page1 = converter.convert(
            [([[0, 0], [100, 0], [100, 20], [0, 20]], ("Page1 text", 0.9))],
            page_number=1,
        )
        page2 = converter.convert(
            [([[0, 0], [100, 0], [100, 20], [0, 20]], ("Page2 text", 0.8))],
            page_number=2,
        )
        merged = converter.merge_page_doctags([page1, page2])

        assert len(merged["content"]["children"]) == 2
        assert merged["content"]["children"][0]["page_number"] == 1
        assert merged["content"]["children"][1]["page_number"] == 2


# ---------------------------------------------------------------------------
# OCREngine tests (mock RapidOCR)
# ---------------------------------------------------------------------------


class TestOCREngineProcessImage:
    """Test OCR engine image processing with mocked RapidOCR."""

    def test_process_image_returns_formatted_results(self, tmp_path: Path) -> None:
        class ArrayLikeBox:
            def tolist(self) -> list[list[int]]:
                return [[0, 0], [100, 0], [100, 20], [0, 20]]

        mock_ocr_instance = MagicMock()
        box = ArrayLikeBox()
        mock_ocr_instance.return_value = (
            [(box, "detected text", 0.95)],
            [10.0, 20.0],
        )
        _mock_rapid.RapidOCR.return_value = mock_ocr_instance

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"fake image data")

        engine = OCREngine()
        results = engine.process_image(str(img_file))

        assert len(results) == 1
        assert results[0][1] == ("detected text", 0.95)

    def test_process_image_empty_result(self, tmp_path: Path) -> None:
        mock_ocr_instance = MagicMock()
        mock_ocr_instance.return_value = (None, [])
        _mock_rapid.RapidOCR.return_value = mock_ocr_instance

        img_file = tmp_path / "blank.png"
        img_file.write_bytes(b"fake")

        engine = OCREngine()
        results = engine.process_image(str(img_file))
        assert results == []

    def test_process_image_file_not_found(self) -> None:
        _mock_rapid.RapidOCR.return_value = MagicMock()
        engine = OCREngine()

        with pytest.raises(FileNotFoundError):
            engine.process_image("/nonexistent/image.png")

    def test_get_model_info(self) -> None:
        _mock_rapid.RapidOCR.return_value = MagicMock()
        engine = OCREngine(model_name="test_model", lang="en")
        info = engine.get_model_info()

        assert info["model_name"] == "test_model"
        assert info["language"] == "en"
        assert info["gpu_available"] is False
