from __future__ import annotations

from app.config.engine_timeout import EngineTimeoutConfig


def test_engine_timeout_defaults_match_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ENGINE_OCR_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_OCR_MAX_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_VLM_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_VLM_MAX_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_TEXT_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_TEXT_MAX_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_MARKITDOWN_TIMEOUT", raising=False)
    monkeypatch.delenv("ENGINE_MARKITDOWN_MAX_TIMEOUT", raising=False)

    config = EngineTimeoutConfig.from_env()

    assert config.ocr.default_timeout_seconds == 60
    assert config.ocr.max_timeout_seconds == 180
    assert config.vlm.default_timeout_seconds == 120
    assert config.vlm.max_timeout_seconds == 300
    assert config.text.default_timeout_seconds == 30
    assert config.text.max_timeout_seconds == 60
    assert config.markitdown.default_timeout_seconds == 30
    assert config.markitdown.max_timeout_seconds == 60


def test_engine_timeout_supports_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ENGINE_OCR_TIMEOUT", "75")
    monkeypatch.setenv("ENGINE_OCR_MAX_TIMEOUT", "210")

    config = EngineTimeoutConfig.from_env()

    assert config.ocr.default_timeout_seconds == 75
    assert config.ocr.max_timeout_seconds == 210


def test_resolve_timeout_applies_page_scaling_with_cap() -> None:
    config = EngineTimeoutConfig.from_env()

    assert config.resolve_timeout_seconds("ocr", page_count=1) == 60
    assert config.resolve_timeout_seconds("ocr", page_count=5) == 180
    assert config.resolve_timeout_seconds("vlm", page_count=2) == 240
    assert config.resolve_timeout_seconds("text", page_count=10) == 60
