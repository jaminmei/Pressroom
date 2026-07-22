# SPDX-License-Identifier: GPL-3.0-only
# engines/text/src/doctags_converter.py
"""
DocTags Converter for Text Engine

Converts Text engine output to DocTags format.
"""

import logging
import time
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DocumentSource(BaseModel):
    """Document source information"""

    filename: str = "unknown"
    mime_type: str = ""
    size_bytes: int = 0


class DocumentStatistics(BaseModel):
    """Document statistics"""

    char_count: int = 0
    word_count: int = 0
    block_count: int = 0
    table_count: int = 0
    figure_count: int = 0


class DocumentMeta(BaseModel):
    """Document metadata"""

    id: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str | DocumentSource] = None
    created_at: Optional[str] = None
    engine_chain: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    page_count: Optional[int] = None
    statistics: Optional[DocumentStatistics] = None


class Block(BaseModel):
    """A single block in the document"""

    id: str
    type: str
    text: str
    level: Optional[int] = None
    confidence: float = 0.9


class DocTagsDocument(BaseModel):
    """DocTags document format"""

    version: str = "1.0"
    meta: DocumentMeta
    blocks: List[Block]


class DocTagsConverter:
    """
    Converts Text engine output to DocTags format
    """

    def __init__(self):
        self.engine_name = "text"

    def convert(self, blocks: List[dict], source_info: Optional[dict] = None) -> dict:
        """
        Convert Text output blocks to DocTags format

        Args:
            blocks: List of blocks from Text engine
            source_info: Optional source information

        Returns:
            DocTags document as dictionary
        """
        char_count = 0
        word_count = 0
        table_count = 0
        figure_count = 0

        converted_blocks = []
        for idx, block in enumerate(blocks):
            block_id = block.get("id", f"block_{idx:03d}")
            block_type = block.get("type", "paragraph")
            text = block.get("text", "")
            level = block.get("level")
            confidence = block.get("confidence", 0.9)

            char_count += len(text)
            word_count += len(text.split())
            if block_type == "table":
                table_count += 1
            elif block_type == "figure":
                figure_count += 1

            converted_blocks.append(
                Block(id=block_id, type=block_type, text=text, level=level, confidence=confidence)
            )

        source = None
        if source_info:
            source = DocumentSource(
                filename=source_info.get("filename", "unknown"),
                mime_type=source_info.get("mime_type", ""),
                size_bytes=source_info.get("size_bytes", 0),
            )

        meta = DocumentMeta(
            id=f"doc_{int(time.time() * 1000)}",
            title=None,
            source=source,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            engine_chain=[self.engine_name],
            language=None,
            page_count=1,
            statistics=DocumentStatistics(
                char_count=char_count,
                word_count=word_count,
                block_count=len(converted_blocks),
                table_count=table_count,
                figure_count=figure_count,
            ),
        )

        doctags = DocTagsDocument(version="1.0", meta=meta, blocks=converted_blocks)

        logger.info(
            f"Converted to DocTags: {len(converted_blocks)} blocks, "
            f"{char_count} chars, {word_count} words"
        )

        return doctags.model_dump()
