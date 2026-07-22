from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class PageInfo(BaseModel):
    page_number: int
    total_pages: int


class ImageSource(BaseModel):
    type: Literal["upload", "pdf_convert", "html_extract"]
    original_filename: str
    original_mime_type: str
    conversion_path: list[str] | None = None


class ImageData(BaseModel):
    file_path: str
    width: int
    height: int
    format: Literal["png", "jpeg", "webp", "bmp", "tiff"]
    size_bytes: int


class ImageInput(BaseModel):
    id: str = Field(default_factory=lambda: f"img_{uuid4()}")
    source: ImageSource
    data: ImageData
    page_info: PageInfo | None = None


class TextSource(BaseModel):
    type: Literal["upload", "html_extract", "plain_text"]
    original_filename: str
    original_mime_type: str
    encoding: Literal["utf-8", "ascii", "big5", "gb2312", "gbk", "utf-16"] = "utf-8"


class TextContent(BaseModel):
    raw: str
    char_count: int
    line_count: int


class TextInput(BaseModel):
    id: str = Field(default_factory=lambda: f"txt_{uuid4()}")
    source: TextSource
    content: TextContent


EngineInput = ImageInput | TextInput
