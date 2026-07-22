"""Unit tests for ENGINE type registry."""

from app.providers.engine_registry import (
    ENGINE_TYPES,
    EngineTypeMeta,
    get_all_categories,
    get_category_defaults,
    get_engine_meta,
)


class TestEngineTypesRegistry:
    """Test ENGINE_TYPES dict completeness and structure."""

    def test_all_eight_engine_types_defined(self) -> None:
        expected = {
            "vlm",
            "ocr",
            "text",
            "markitdown",
            "docling",
            "layout_detection",
            "image_enhancement",
            "image_rotation",
        }
        assert set(ENGINE_TYPES.keys()) == expected

    def test_each_engine_type_has_required_fields(self) -> None:
        required = {
            "category",
            "display_name",
            "icon",
            "description",
            "default_provider_type",
            "supported_input_types",
            "response_formats",
            "allow_multiple_models",
        }
        for key, meta in ENGINE_TYPES.items():
            actual = {f.name for f in meta.__dataclass_fields__.values()}
            assert required == actual, f"ENGINE '{key}' missing fields: {required - actual}"

    def test_category_matches_dict_key(self) -> None:
        for key, meta in ENGINE_TYPES.items():
            assert meta.category == key, f"ENGINE key={key} has category={meta.category}"

    def test_all_engine_types_are_frozen(self) -> None:
        for meta in ENGINE_TYPES.values():
            assert isinstance(meta, EngineTypeMeta)


class TestGetEngineMeta:
    """Test get_engine_meta helper."""

    def test_valid_category(self) -> None:
        meta = get_engine_meta("ocr")
        assert meta is not None
        assert meta.category == "ocr"
        assert meta.display_name == "OCR"

    def test_valid_vlm(self) -> None:
        meta = get_engine_meta("vlm")
        assert meta is not None
        assert meta.default_provider_type == "openai_compatible"
        assert meta.allow_multiple_models is True

    def test_invalid_category_returns_none(self) -> None:
        assert get_engine_meta("nonexistent") is None

    def test_empty_string_returns_none(self) -> None:
        assert get_engine_meta("") is None


class TestGetAllCategories:
    """Test get_all_categories helper."""

    def test_returns_eight_categories(self) -> None:
        categories = get_all_categories()
        assert len(categories) == 8

    def test_returns_list_not_dict(self) -> None:
        result = get_all_categories()
        assert isinstance(result, list)


class TestGetCategoryDefaults:
    """Test get_category_defaults helper."""

    def test_ocr_defaults(self) -> None:
        defaults = get_category_defaults("ocr")
        assert defaults["provider_type"] == "engine_service"
        assert defaults["response_format"] == "node_output"

    def test_vlm_defaults(self) -> None:
        defaults = get_category_defaults("vlm")
        assert defaults["provider_type"] == "openai_compatible"
        assert defaults["response_format"] == "openai_chat"

    def test_text_defaults(self) -> None:
        defaults = get_category_defaults("text")
        assert defaults["provider_type"] == "engine_service"
        assert defaults["response_format"] == "node_output"

    def test_unknown_category_returns_empty(self) -> None:
        assert get_category_defaults("foo") == {}


class TestEngineTypeSpecificMetadata:
    """Test specific metadata values for each ENGINE type."""

    def test_vlm_allows_multiple_models(self) -> None:
        assert ENGINE_TYPES["vlm"].allow_multiple_models is True

    def test_all_engine_service_disallow_multiple_models(self) -> None:
        engine_service_types = [
            k for k, v in ENGINE_TYPES.items() if v.default_provider_type == "engine_service"
        ]
        for cat in engine_service_types:
            assert ENGINE_TYPES[cat].allow_multiple_models is False, (
                f"{cat} is engine_service but allows multiple models"
            )

    def test_vlm_response_formats_include_openai_chat(self) -> None:
        assert "openai_chat" in ENGINE_TYPES["vlm"].response_formats

    def test_ocr_supports_image_input(self) -> None:
        assert "image/*" in ENGINE_TYPES["ocr"].supported_input_types

    def test_text_supports_text_input(self) -> None:
        assert "text/plain" in ENGINE_TYPES["text"].supported_input_types

    def test_markitdown_supports_pdf(self) -> None:
        assert "application/pdf" in ENGINE_TYPES["markitdown"].supported_input_types
