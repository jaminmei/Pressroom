# engines/docling/src/docling_engine.py
"""
Docling Engine

Uses IBM's Docling to convert various document formats to Markdown.
Supports: PDF, DOCX, PPTX, HTML, images, and plain text formats.
"""

import logging
from pathlib import Path
from typing import List, Optional

from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


class DoclingEngine:
    """
    Docling Engine for multi-format document conversion.

    Converts documents to Markdown using the Docling library.
    Unlike MarkItDown, Docling produces clean markdown directly,
    so no additional block parsing is needed.
    """

    # Supported formats
    SUPPORTED_EXTENSIONS = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
    }

    def __init__(self):
        logger.info("Initializing Docling engine...")
        self.converter = DocumentConverter()
        logger.info("Docling engine initialized successfully")

    def process_file(self, file_path: str, config: Optional[dict] = None) -> str:
        """
        Process a file and return markdown text

        Args:
            file_path: Path to the file
            config: Optional configuration (currently unused)

        Returns:
            Markdown string produced by Docling
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Convert to markdown
        result = self.converter.convert(file_path)
        markdown_text = result.document.export_to_markdown()

        logger.info("Document processed chars_extracted=%d", len(markdown_text))
        return markdown_text

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
            "engine": "docling",
            "model": "IBM Docling",
            "supported_formats": list(self.SUPPORTED_EXTENSIONS.keys()),
            "gpu_available": False,
        }
