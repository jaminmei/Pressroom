from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class EngineTimeout(BaseModel):
    default_timeout_seconds: int = Field(ge=1)
    max_timeout_seconds: int = Field(ge=1)


class EngineTimeoutConfig(BaseModel):
    ocr: EngineTimeout = Field(
        default_factory=lambda: EngineTimeout(default_timeout_seconds=60, max_timeout_seconds=180)
    )
    vlm: EngineTimeout = Field(
        default_factory=lambda: EngineTimeout(default_timeout_seconds=120, max_timeout_seconds=300)
    )
    text: EngineTimeout = Field(
        default_factory=lambda: EngineTimeout(default_timeout_seconds=30, max_timeout_seconds=60)
    )
    markitdown: EngineTimeout = Field(
        default_factory=lambda: EngineTimeout(default_timeout_seconds=30, max_timeout_seconds=60)
    )

    @classmethod
    def from_env(cls) -> "EngineTimeoutConfig":
        return cls(
            ocr=EngineTimeout(
                default_timeout_seconds=_read_int_env("ENGINE_OCR_TIMEOUT", 60),
                max_timeout_seconds=_read_int_env("ENGINE_OCR_MAX_TIMEOUT", 180),
            ),
            vlm=EngineTimeout(
                default_timeout_seconds=_read_int_env("ENGINE_VLM_TIMEOUT", 120),
                max_timeout_seconds=_read_int_env("ENGINE_VLM_MAX_TIMEOUT", 300),
            ),
            text=EngineTimeout(
                default_timeout_seconds=_read_int_env("ENGINE_TEXT_TIMEOUT", 30),
                max_timeout_seconds=_read_int_env("ENGINE_TEXT_MAX_TIMEOUT", 60),
            ),
            markitdown=EngineTimeout(
                default_timeout_seconds=_read_int_env("ENGINE_MARKITDOWN_TIMEOUT", 30),
                max_timeout_seconds=_read_int_env("ENGINE_MARKITDOWN_MAX_TIMEOUT", 60),
            ),
        )

    def resolve_timeout_seconds(self, engine_type: str, *, page_count: int = 1) -> int:
        timeout = self._for_engine(engine_type)
        normalized_pages = max(page_count, 1)
        return min(timeout.default_timeout_seconds * normalized_pages, timeout.max_timeout_seconds)

    def _for_engine(self, engine_type: str) -> EngineTimeout:
        normalized = engine_type.lower().strip()
        mapping = {
            "ocr": self.ocr,
            "vlm": self.vlm,
            "text": self.text,
            "markitdown": self.markitdown,
        }
        if normalized not in mapping:
            raise ValueError(f"Unsupported engine type: {engine_type}")
        return mapping[normalized]


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@lru_cache
def get_engine_timeout_config() -> EngineTimeoutConfig:
    return EngineTimeoutConfig.from_env()
