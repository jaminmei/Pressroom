from __future__ import annotations

from pydantic import BaseModel, Field


class OutputMetadata(BaseModel):
    processing_time_ms: int
    page_count: int
    char_count: int
    word_count: int
    confidence: float | None = None
    engine_chain: list[str] = Field(default_factory=list)
    source_filename: str


class OutputResult(BaseModel):
    format: str
    content_type: str
    text: str
    metadata: OutputMetadata
