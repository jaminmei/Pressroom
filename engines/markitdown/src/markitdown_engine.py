# engines/markitdown/src/markitdown_engine.py
"""
MarkItDown Engine

Uses Microsoft's MarkItDown to convert various document formats to Markdown.
Supports: PDF, DOCX, PPTX, XLSX, HTML, and more.
"""

import base64
import logging
import re
import tempfile
from pathlib import Path
from typing import List, Optional

from markitdown import MarkItDown

logger = logging.getLogger(__name__)


class MarkItDownEngine:
    """
    MarkItDown Engine for multi-format document conversion.

    Converts documents to Markdown, then parses into structured blocks.
    """

    # Supported formats
    SUPPORTED_EXTENSIONS = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
    }

    def __init__(self):
        logger.info("Initializing MarkItDown engine...")
        self.converter = MarkItDown()
        logger.info("MarkItDown engine initialized successfully")

    def process_file(self, file_path: str, config: Optional[dict] = None) -> List[dict]:
        """
        Process a file and return structured blocks

        Args:
            file_path: Path to the file
            config: Optional configuration

        Returns:
            List of blocks: [{id, type, text, level?, confidence}, ...]
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Convert to markdown
        result = self.converter.convert(file_path)
        markdown_text = result.text_content

        # Parse markdown to blocks
        blocks = self._parse_markdown(markdown_text)

        logger.info("Document processed blocks_extracted=%d", len(blocks))
        return blocks

    def process_base64(
        self, base64_data: str, file_extension: str = ".txt", config: Optional[dict] = None
    ) -> List[dict]:
        """
        Process base64 encoded file content

        Args:
            base64_data: Base64 encoded file content
            file_extension: File extension (e.g., '.pdf', '.docx')
            config: Optional configuration

        Returns:
            List of blocks
        """
        # Decode and save to temp file
        file_data = base64.b64decode(base64_data)

        # Determine extension
        if not file_extension.startswith("."):
            file_extension = "." + file_extension

        with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as f:
            f.write(file_data)
            temp_path = f.name

        try:
            return self.process_file(temp_path, config)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _parse_markdown(self, markdown_text: str) -> List[dict]:
        """Parse Markdown text into structured blocks"""
        blocks = []
        block_id = 0

        lines = markdown_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Skip empty lines
            if not line.strip():
                i += 1
                continue

            # Headings
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "title",
                        "text": text,
                        "level": level,
                        "confidence": 0.95,
                    }
                )
                block_id += 1
                i += 1
                continue

            # Code blocks
            if line.strip().startswith("```"):
                code_lines = []
                i += 1  # Skip opening ```
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # Skip closing ```

                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "paragraph",
                        "text": "```\n" + "\n".join(code_lines) + "\n```",
                        "confidence": 0.95,
                    }
                )
                block_id += 1
                continue

            # Tables (look for | patterns)
            if "|" in line and i + 1 < len(lines) and "|" in lines[i + 1]:
                table_lines = [line]
                i += 1
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1

                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "table",
                        "text": "\n".join(table_lines),
                        "confidence": 0.9,
                    }
                )
                block_id += 1
                continue

            # Lists
            if re.match(r"^[-*+]\s+", line) or re.match(r"^\d+\.\s+", line):
                list_lines = [line]
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if re.match(r"^[-*+]\s+", next_line) or re.match(r"^\d+\.\s+", next_line):
                        list_lines.append(next_line)
                        i += 1
                    elif next_line.strip() == "":
                        i += 1
                    else:
                        break

                blocks.append(
                    {
                        "id": f"block_{block_id:03d}",
                        "type": "list",
                        "text": "\n".join(list_lines),
                        "confidence": 0.9,
                    }
                )
                block_id += 1
                continue

            # Regular paragraph
            paragraph_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if (
                    next_line.strip() == ""
                    or re.match(r"^#{1,6}\s+", next_line)
                    or re.match(r"^[-*+]\s+", next_line)
                    or re.match(r"^\d+\.\s+", next_line)
                    or "|" in next_line
                    or next_line.strip().startswith("```")
                ):
                    break
                paragraph_lines.append(next_line)
                i += 1

            blocks.append(
                {
                    "id": f"block_{block_id:03d}",
                    "type": "paragraph",
                    "text": "\n".join(paragraph_lines),
                    "confidence": 0.9,
                }
            )
            block_id += 1

        return blocks

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions"""
        return list(self.SUPPORTED_EXTENSIONS.keys())

    def is_supported(self, extension: str) -> bool:
        """Check if file extension is supported"""
        if not extension.startswith("."):
            extension = "." + extension
        return extension.lower() in self.SUPPORTED_EXTENSIONS

    def get_model_info(self) -> dict:
        """Get engine information"""
        return {
            "engine": "markitdown",
            "model": "Microsoft MarkItDown",
            "supported_formats": list(self.SUPPORTED_EXTENSIONS.keys()),
            "gpu_available": False,
        }
