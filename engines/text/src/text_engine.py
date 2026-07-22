# SPDX-License-Identifier: GPL-3.0-only
# engines/text/src/text_engine.py
"""
Text Engine

Processes plain text and HTML content, extracts structure, outputs structured blocks.
"""

import base64
import logging
import re
from typing import Any, List, Optional

import html2text
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


class TextEngine:
    """
    Text Engine for processing plain text and HTML content.

    Detects document structure (titles, paragraphs, lists, tables)
    and outputs structured blocks.
    """

    def __init__(self):
        self.html2text_converter = html2text.HTML2Text()
        self.html2text_converter.ignore_links = False
        self.html2text_converter.ignore_images = False
        self.html2text_converter.body_width = 0  # No line wrapping

        logger.info("Text Engine initialized")

    def process_text(self, text: str, config: Optional[dict] = None) -> List[dict]:
        """
        Process plain text content

        Args:
            text: Plain text content
            config: Optional configuration

        Returns:
            List of blocks: [{id, type, text, level?, confidence}, ...]
        """
        blocks = self._parse_plain_text(text)
        logger.info(f"Processed plain text: {len(blocks)} blocks extracted")
        return blocks

    def process_html(self, html_content: str, config: Optional[dict] = None) -> List[dict]:
        """
        Process HTML content

        Args:
            html_content: HTML content string
            config: Optional configuration

        Returns:
            List of blocks: [{id, type, text, level?, confidence}, ...]
        """
        blocks = self._parse_html(html_content)
        logger.info(f"Processed HTML: {len(blocks)} blocks extracted")
        return blocks

    def process_base64(
        self, base64_data: str, input_format: str = "text", config: Optional[dict] = None
    ) -> List[dict]:
        """
        Process base64 encoded content

        Args:
            base64_data: Base64 encoded content
            input_format: 'text' or 'html'
            config: Optional configuration

        Returns:
            List of blocks
        """
        content = self._decode_base64_content(base64_data, config=config)

        if input_format == "html":
            return self.process_html(content, config)
        else:
            return self.process_text(content, config)

    def _decode_base64_content(self, base64_data: str, config: Optional[dict] = None) -> str:
        """Decode base64 text payload with UTF-8 first, then legacy-safe fallbacks."""
        raw_bytes = base64.b64decode(base64_data)

        candidates: List[str] = []
        configured_encoding = None
        if isinstance(config, dict):
            value = config.get("encoding")
            if isinstance(value, str) and value.strip():
                configured_encoding = value.strip()
        if configured_encoding:
            candidates.append(configured_encoding)

        candidates.extend(["utf-8", "utf-8-sig", "big5", "gbk", "gb2312"])

        # Only attempt UTF-16 autodetection when BOM is present to avoid false positives.
        if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
            candidates.extend(["utf-16", "utf-16-le", "utf-16-be"])

        seen: set[str] = set()
        for encoding in candidates:
            key = encoding.lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                return raw_bytes.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue

        logger.warning(
            "Unable to decode base64 payload with known encodings; using UTF-8 replacement fallback"
        )
        return raw_bytes.decode("utf-8", errors="replace")

    def _parse_plain_text(self, text: str) -> List[dict[str, Any]]:
        """Parse plain text into structured blocks"""
        blocks: List[dict[str, Any]] = []
        lines = text.split("\n")
        block_id = 0

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Detect title (all caps, short line, or starts with #)
            if self._is_title(line):
                level = self._detect_title_level(line)
                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "title",
                        "text": line.lstrip("#").strip(),
                        "level": level,
                        "confidence": 0.9,
                    }
                )
                block_id += 1

            # Detect list (starts with -, *, 1., etc.)
            elif self._is_list_item(line):
                list_items = [line]
                while i + 1 < len(lines) and self._is_list_item(lines[i + 1].strip()):
                    i += 1
                    list_items.append(lines[i].strip())

                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "list",
                        "text": "\n".join(list_items),
                        "confidence": 0.85,
                    }
                )
                block_id += 1

            # Regular paragraph
            else:
                paragraph_lines = [line]
                while i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if not next_line or self._is_title(next_line) or self._is_list_item(next_line):
                        break
                    i += 1
                    paragraph_lines.append(next_line)

                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "paragraph",
                        "text": "\n".join(paragraph_lines),
                        "confidence": 0.95,
                    }
                )
                block_id += 1

            i += 1

        return blocks

    def _parse_html(self, html_content: str) -> List[dict[str, Any]]:
        """Parse HTML into structured blocks"""
        blocks: List[dict[str, Any]] = []
        block_id = 0

        soup = BeautifulSoup(html_content, "lxml")

        # Remove script and style elements
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()

        # Parse full body to avoid dropping sibling semantic roots or body-level content.
        body = soup.body if soup.body else soup

        for element in body.descendants:
            if not isinstance(element, Tag):
                continue

            if self._should_skip_element(element):
                continue

            block: dict[str, Any] | None = None

            # Titles
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(element.name[1])
                text = element.get_text(strip=True)
                if text:
                    block = {
                        "id": f"block_{block_id:03d}",
                        "type": "title",
                        "text": text,
                        "level": level,
                        "confidence": 0.95,
                    }

            # Paragraphs
            elif element.name == "p":
                text = element.get_text(" ", strip=True)
                if text:
                    block = {
                        "id": f"block_{block_id:03d}",
                        "type": "paragraph",
                        "text": text,
                        "confidence": 0.95,
                    }

            # Lists
            elif element.name in ["ul", "ol"]:
                items = [li.get_text(strip=True) for li in element.find_all("li", recursive=False)]
                if items:
                    block = {
                        "id": f"block_{block_id:03d}",
                        "type": "list",
                        "text": "\n".join(f"- {item}" for item in items),
                        "confidence": 0.9,
                    }

            # Tables
            elif element.name == "table":
                table_md = self._convert_table_to_markdown(element)
                if table_md:
                    block = {
                        "id": f"block_{block_id:03d}",
                        "type": "table",
                        "text": table_md,
                        "confidence": 0.9,
                    }

            # Code blocks
            elif element.name in ["pre", "code"]:
                text = element.get_text()
                if text and len(text) > 10:
                    block = {
                        "id": f"block_{block_id:03d}",
                        "type": "paragraph",
                        "text": f"```\n{text}\n```",
                        "confidence": 0.9,
                    }

            if block:
                blocks.append(block)
                block_id += 1

        # Remove duplicates from nested structures.
        seen_texts: set[tuple[str, str, str]] = set()
        unique_blocks: List[dict[str, Any]] = []
        for block in blocks:
            text_value = block.get("text", "")
            if not isinstance(text_value, str):
                continue
            normalized_text = " ".join(text_value.split())
            text_key = (
                str(block.get("type", "paragraph")),
                str(block.get("level", "")),
                normalized_text,
            )
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                unique_blocks.append(block)

        return unique_blocks

    def _is_title(self, line: str) -> bool:
        """Check if line is a title"""
        if line.startswith("#"):
            return True
        if len(line) < 100 and line.isupper():
            return True
        return False

    def _detect_title_level(self, line: str) -> int:
        """Detect title level from markdown-style heading"""
        if line.startswith("#"):
            count = len(line) - len(line.lstrip("#"))
            return min(count, 6)
        return 1

    def _is_list_item(self, line: str) -> bool:
        """Check if line is a list item"""
        patterns = [
            r"^[-*+]\s",  # Unordered list
            r"^\d+\.\s",  # Ordered list
            r"^[a-z]\)\s",  # Letter list
        ]
        return any(re.match(p, line) for p in patterns)

    def _should_skip_element(self, element: Tag) -> bool:
        """Skip nested tags that would duplicate parent block content."""
        parent = element.parent
        if not isinstance(parent, Tag):
            return False

        if element.name == "code" and parent.name == "pre":
            return True
        if element.name == "p" and parent.name in {"li", "td", "th"}:
            return True
        if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"} and parent.name in {
            "header",
            "footer",
        }:
            return True
        return False

    def _convert_table_to_markdown(self, table_element: Tag) -> str:
        """Convert HTML table to Markdown format"""
        rows = []
        for tr in table_element.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = [
                td.get_text(strip=True) for td in tr.find_all(["th", "td"]) if isinstance(td, Tag)
            ]
            if cells:
                rows.append("| " + " | ".join(cells) + " |")

        if not rows:
            return ""

        # Add header separator
        if len(rows) > 1:
            num_cols = rows[0].count("|") - 1
            separator = "|" + "|".join(["---"] * num_cols) + "|"
            rows.insert(1, separator)

        return "\n".join(rows)

    def get_model_info(self) -> dict:
        """Get engine information"""
        return {
            "engine": "text",
            "model": "rule-based",
            "supported_formats": ["text", "html"],
            "gpu_available": False,
        }
