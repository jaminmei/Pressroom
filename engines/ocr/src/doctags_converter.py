"""
Convert OCR results to DocTags format

DocTags is a unified intermediate format for document content representation.

"""

import logging
import time
import uuid
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class DocTagsConverter:
    """
    Convert OCR results to DocTags format.

    DocTags is a structured format that represents document content
    with metadata, content blocks, and statistics.
    """

    # Supported MIME types for image files
    MIME_TYPES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }

    def convert(
        self,
        ocr_result: List[Any],
        source_path: Optional[str] = None,
        page_number: Optional[int] = None,
    ) -> dict:
        """
        Convert OCR result to DocTags format.

        Args:
            ocr_result: OCR result from PaddleOCR
                        Format: [[box, (text, confidence)], ...]
            source_path: Optional source file path for metadata
            page_number: Optional page number (for multi-page documents)

        Returns:
            DocTags document as dictionary
        """
        doc_id = str(uuid.uuid4())
        blocks = []

        # Process each detected text line
        for idx, line in enumerate(ocr_result):
            if len(line) != 2:
                logger.warning("Unexpected OCR result format index=%d", idx)
                continue

            box, text_conf = line

            if len(text_conf) != 2:
                logger.warning(f"Unexpected text/confidence format at index {idx}")
                continue

            text, confidence = text_conf

            # Build block
            block = self._create_block(
                block_id=f"block_{idx:03d}",
                text=text,
                box=box,
                confidence=confidence,
                page_number=page_number,
            )
            blocks.append(block)

        # Calculate statistics
        statistics = self._calculate_statistics(blocks)

        # Build source info
        source_info = self._build_source_info(source_path)

        # Build DocTags document
        doctags = {
            "meta": {
                "id": f"doc_{doc_id}",
                "source": source_info,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "engine_chain": ["ocr"],
                "statistics": statistics,
            },
            "content": {"type": "doc", "children": blocks},
        }

        # Add page info if provided
        if page_number is not None:
            doctags["pages"] = [{"number": page_number}]

        logger.debug(
            f"Converted to DocTags: {len(blocks)} blocks, "
            f"{statistics['char_count']} chars, "
            f"{statistics['word_count']} words"
        )

        return doctags

    def _create_block(
        self,
        block_id: str,
        text: str,
        box: List[List[float]],
        confidence: float,
        page_number: Optional[int] = None,
    ) -> dict:
        """
        Create a content block from OCR result.

        Args:
            block_id: Unique identifier for the block
            text: Extracted text
            box: Bounding box coordinates [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            confidence: OCR confidence score
            page_number: Optional page number

        Returns:
            Block dictionary
        """
        block = {
            "id": block_id,
            "type": "paragraph",  # OCR defaults to paragraph type
            "text": text,
            "confidence": float(confidence),
            "source": {"engine": "ocr", "model": "rapidocr-onnx"},
        }

        # Add bounding box if available
        if box and len(box) >= 4:
            try:
                block["bbox"] = {
                    "x": int(box[0][0]),
                    "y": int(box[0][1]),
                    "width": int(box[2][0] - box[0][0]),
                    "height": int(box[2][1] - box[0][1]),
                }
            except (IndexError, TypeError) as e:
                logger.warning("Bounding box parsing failed error_type=%s", type(e).__name__)

        # Add page number if provided
        if page_number is not None:
            block["page_number"] = page_number

        return block

    def _calculate_statistics(self, blocks: List[dict]) -> dict:
        """
        Calculate document statistics from blocks.

        Args:
            blocks: List of content blocks

        Returns:
            Statistics dictionary
        """
        char_count = 0
        word_count = 0

        for block in blocks:
            text = block.get("text", "")
            char_count += len(text)
            word_count += len(text.split())

        return {
            "char_count": char_count,
            "word_count": word_count,
            "block_count": len(blocks),
            "table_count": 0,  # OCR alone cannot detect tables
            "figure_count": 0,  # OCR alone cannot detect figures
        }

    def _build_source_info(self, source_path: Optional[str]) -> dict:
        """
        Build source information from file path.

        Args:
            source_path: Path to source file

        Returns:
            Source info dictionary
        """
        default_info = {"filename": "unknown", "mime_type": "image/png", "size_bytes": 0}

        if not source_path:
            return default_info

        path = Path(source_path)

        if not path.exists():
            return {**default_info, "filename": path.name}

        # Get MIME type from extension
        ext = path.suffix.lower()
        mime_type = self.MIME_TYPES.get(ext, "application/octet-stream")

        return {"filename": path.name, "mime_type": mime_type, "size_bytes": path.stat().st_size}

    def merge_page_doctags(
        self, page_doctags: List[dict], source_info: Optional[dict] = None
    ) -> dict:
        """
        Merge multiple page DocTags into a single document.

        Args:
            page_doctags: List of DocTags for each page
            source_info: Optional source info override

        Returns:
            Merged DocTags document
        """
        if not page_doctags:
            return {
                "meta": {
                    "id": f"doc_{uuid.uuid4()}",
                    "source": source_info or {},
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "engine_chain": ["ocr"],
                    "statistics": {
                        "char_count": 0,
                        "word_count": 0,
                        "block_count": 0,
                        "table_count": 0,
                        "figure_count": 0,
                    },
                },
                "content": {"type": "doc", "children": []},
                "pages": [],
            }

        merged_id = f"doc_{uuid.uuid4()}"
        all_blocks = []
        pages_info = []

        # Aggregate statistics
        total_stats = {
            "char_count": 0,
            "word_count": 0,
            "block_count": 0,
            "table_count": 0,
            "figure_count": 0,
        }

        for page_idx, page_doc in enumerate(page_doctags):
            page_number = page_idx + 1

            # Collect blocks with page number
            for block in page_doc.get("content", {}).get("children", []):
                block["page_number"] = page_number
                all_blocks.append(block)

            # Collect page info
            if "pages" in page_doc and page_doc["pages"]:
                pages_info.extend(page_doc["pages"])
            else:
                pages_info.append({"number": page_number})

            # Aggregate statistics
            stats = page_doc.get("meta", {}).get("statistics", {})
            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

        # Build merged source info
        if source_info is None:
            source_info = page_doctags[0].get("meta", {}).get("source", {})

        return {
            "meta": {
                "id": merged_id,
                "source": source_info,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "engine_chain": ["ocr"],
                "statistics": total_stats,
            },
            "content": {"type": "doc", "children": all_blocks},
            "pages": pages_info,
        }
