from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import yaml

from app.models.execution import NodeOutput
from app.models.output import OutputMetadata, OutputResult
from app.services.output_formatter.base import FormatterContext, OutputFormatter

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


@dataclass
class _Stats:
    char_count: int = 0
    word_count: int = 0
    confidence_values: list[float] = field(default_factory=list)


class YamlFormatter(OutputFormatter):
    """Render NodeOutput to machine-readable YAML output."""

    def format(
        self,
        document: NodeOutput,
        config: dict,
        context: FormatterContext,
    ) -> OutputResult:
        start = perf_counter()

        blocks = self._get_blocks(document)
        stats = _Stats()

        content: list[dict[str, Any]] = []
        if blocks:
            flattened_blocks = self._flatten_blocks(blocks)
            for index, block in enumerate(flattened_blocks, start=1):
                serialized = self._serialize_block(block, index)
                if serialized is None:
                    continue
                content.append(serialized)

                visible_text = self._extract_visible_text(block)
                if visible_text:
                    stats.char_count += self._count_visible_chars(visible_text)
                    stats.word_count += self._count_words(visible_text)
                confidence = block.get("confidence")
                if isinstance(confidence, (int, float)) and visible_text:
                    stats.confidence_values.append(float(confidence))

        doc_meta = document.metadata
        confidence = self._average_confidence(stats.confidence_values)
        payload: dict[str, Any] = {
            "document": {
                "title": self._resolve_title(document, context.source_filename),
                "source": context.source_filename,
                "engine_chain": context.engine_chain or doc_meta.get("engine_chain", []),
                "created_at": doc_meta.get("created_at") or self._now_iso(),
                "metadata": {
                    "page_count": self._resolve_page_count(document),
                    "char_count": stats.char_count,
                    "word_count": stats.word_count,
                },
            },
        }

        # Include text content if present
        if document.text:
            payload["document"]["text"] = document.text

        # Include structured content if present
        if document.structured:
            payload["document"]["structured"] = document.structured

        # Include block-level content if rendered
        if content:
            payload["content"] = content

        # Include binary refs if present
        if document.binary:
            payload["document"]["binary"] = [
                {"ref": b.ref, "mime_type": b.mime_type, "size_bytes": b.size_bytes}
                for b in document.binary
            ]

        if confidence is not None:
            payload["document"]["metadata"]["confidence"] = confidence

        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        metadata = OutputMetadata(
            processing_time_ms=max(int((perf_counter() - start) * 1000), 0),
            page_count=self._resolve_page_count(document),
            char_count=stats.char_count,
            word_count=stats.word_count,
            confidence=confidence,
            engine_chain=context.engine_chain or doc_meta.get("engine_chain", []),
            source_filename=context.source_filename,
        )
        return OutputResult(
            format="yaml",
            content_type="application/x-yaml; charset=utf-8",
            text=text,
            metadata=metadata,
        )

    def _get_blocks(self, document: NodeOutput) -> list[dict[str, Any]]:
        """Extract block list from NodeOutput.

        Checks document.structured for a ``blocks`` key first,
        then a ``children`` key, returning whichever list is found.
        """
        if document.structured and isinstance(document.structured, dict):
            blocks = document.structured.get("blocks")
            if isinstance(blocks, list):
                return blocks
            children = document.structured.get("children")
            if isinstance(children, list):
                return children
        return []

    def _flatten_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flat: list[dict[str, Any]] = []
        for block in blocks:
            block_type = str(block.get("type", "")).lower()
            if block_type == "section":
                heading = block.get("heading")
                heading_block = self._section_heading_to_block(heading, block)
                if heading_block:
                    flat.append(heading_block)
                children_raw = block.get("children", [])
                children = [child for child in children_raw if isinstance(child, dict)]
                flat.extend(self._flatten_blocks(children))
                continue
            flat.append(block)
        return flat

    def _section_heading_to_block(
        self,
        heading: Any,
        section_block: dict[str, Any],
    ) -> dict[str, Any] | None:
        if isinstance(heading, dict):
            heading_text = str(heading.get("text", "")).strip()
            if not heading_text:
                return None
            return {
                "type": "title",
                "text": heading_text,
                "level": heading.get("level", 2),
                "page_number": heading.get("page_number", section_block.get("page_number")),
                "confidence": heading.get("confidence", section_block.get("confidence")),
            }
        if isinstance(heading, str) and heading.strip():
            return {
                "type": "title",
                "text": heading.strip(),
                "level": self._as_int(section_block.get("level")) or 2,
                "page_number": section_block.get("page_number"),
                "confidence": section_block.get("confidence"),
            }
        return None

    def _serialize_block(self, block: dict[str, Any], index: int) -> dict[str, Any] | None:
        block_type = str(block.get("type", "")).lower()
        if block_type in {"header", "footer"}:
            return None

        item: dict[str, Any] = {
            "id": str(block.get("id", f"block_{index:03d}")),
            "type": block_type,
        }
        page = self._as_int(block.get("page_number"))
        if page is not None:
            item["page"] = page

        if block_type == "title":
            item["level"] = self._as_int(block.get("level")) or 1
            item["text"] = str(block.get("text", "")).strip()
            return item

        if block_type == "paragraph":
            item["text"] = str(block.get("text", "")).strip()
            return item

        if block_type == "list":
            item["list_type"] = str(block.get("list_type", "unordered")).lower()
            item["items"] = self._normalize_list_items(block.get("items", []))
            return item

        if block_type == "table":
            headers = self._to_row_strings(block.get("headers", []))
            rows = self._to_rows(block.get("rows", []))
            if not headers and rows:
                headers = rows[0]
                rows = rows[1:]
            item["headers"] = headers
            item["rows"] = rows
            caption = str(block.get("caption", "")).strip()
            if caption:
                item["caption"] = caption
            item["text"] = self._table_to_gfm(headers, rows)
            return item

        if block_type == "figure":
            caption = str(block.get("caption", "")).strip()
            alt_text = str(block.get("alt_text", "")).strip()
            if caption:
                item["caption"] = caption
            if alt_text:
                item["alt_text"] = alt_text
            image_ref = block.get("image_ref")
            if isinstance(image_ref, dict):
                item["image_ref"] = image_ref
            elif isinstance(image_ref, str):
                item["image_ref"] = {"path": image_ref}
            return item

        if block_type == "code":
            language = str(block.get("language", "")).strip()
            if language:
                item["language"] = language
            item["text"] = str(block.get("code", block.get("text", ""))).strip()
            return item

        if block_type == "footnote":
            marker = str(block.get("marker", "")).strip()
            if marker:
                item["marker"] = marker
            item["text"] = str(block.get("text", "")).strip()
            return item

        if block_type == "field":
            field_name = str(block.get("field_name", "")).strip()
            text = str(block.get("text", "")).strip()
            if field_name:
                item["field_name"] = field_name
            if text:
                item["text"] = text
            return item

        text = str(block.get("text", "")).strip()
        if text:
            item["text"] = text
            return item
        return None

    def _normalize_list_items(self, items_raw: Any) -> list[dict[str, Any]]:
        if not isinstance(items_raw, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in items_raw:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized.append({"text": text})
                continue
            if not isinstance(item, dict):
                continue

            entry: dict[str, Any] = {}
            text = str(item.get("text", "")).strip()
            if text:
                entry["text"] = text

            children = self._normalize_list_items(item.get("children", []))
            if children:
                entry["children"] = children

            if entry:
                normalized.append(entry)

        return normalized

    def _table_to_gfm(self, headers: list[str], rows: list[list[str]]) -> str:
        if not headers:
            return ""

        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in rows)
        return "\n".join(lines)

    def _extract_visible_text(self, block: dict[str, Any]) -> str:
        block_type = str(block.get("type", "")).lower()

        if block_type in {"title", "paragraph"}:
            return str(block.get("text", "")).strip()
        if block_type == "footnote":
            marker = str(block.get("marker", "")).strip()
            text = str(block.get("text", "")).strip()
            return f"{marker} {text}".strip()
        if block_type == "list":
            return " ".join(self._extract_list_texts(block.get("items", []))).strip()
        if block_type == "table":
            headers = " ".join(self._to_row_strings(block.get("headers", [])))
            rows = " ".join(" ".join(row) for row in self._to_rows(block.get("rows", [])))
            caption = str(block.get("caption", "")).strip()
            return " ".join(part for part in [headers, rows, caption] if part).strip()
        if block_type == "figure":
            caption = str(block.get("caption", "")).strip()
            alt_text = str(block.get("alt_text", "")).strip()
            return " ".join(part for part in [alt_text, caption] if part).strip()
        if block_type == "code":
            return str(block.get("code", block.get("text", ""))).strip()
        if block_type == "field":
            field_name = str(block.get("field_name", "")).strip()
            text = str(block.get("text", "")).strip()
            if field_name and text:
                return f"{field_name}: {text}"
            return text
        return str(block.get("text", "")).strip()

    def _extract_list_texts(self, items_raw: Any) -> list[str]:
        if not isinstance(items_raw, list):
            return []

        texts: list[str] = []
        for item in items_raw:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    texts.append(stripped)
                continue
            if not isinstance(item, dict):
                continue

            item_text = str(item.get("text", "")).strip()
            if item_text:
                texts.append(item_text)
            texts.extend(self._extract_list_texts(item.get("children", [])))

        return texts

    def _to_row_strings(self, row: Any) -> list[str]:
        if not isinstance(row, list):
            return []
        return [self._cell_to_string(cell) for cell in row]

    def _to_rows(self, rows_raw: Any) -> list[list[str]]:
        if not isinstance(rows_raw, list):
            return []

        rows: list[list[str]] = []
        for row in rows_raw:
            if isinstance(row, list):
                rows.append([self._cell_to_string(cell) for cell in row])
            elif isinstance(row, dict):
                cells = row.get("cells", [])
                if isinstance(cells, list):
                    rows.append([self._cell_to_string(cell) for cell in cells])
        return rows

    def _cell_to_string(self, cell: Any) -> str:
        if isinstance(cell, dict):
            return str(cell.get("text", "")).strip()
        return str(cell).strip()

    def _resolve_title(self, document: NodeOutput, source_filename: str) -> str:
        blocks = self._get_blocks(document)
        if blocks:
            discovered = self._find_first_title(blocks)
            if discovered:
                return discovered
        title = document.metadata.get("title")
        if title:
            return str(title)
        return source_filename

    def _find_first_title(self, blocks: list[dict[str, Any]]) -> str | None:
        for block in blocks:
            block_type = str(block.get("type", "")).lower()
            if block_type == "title":
                title = str(block.get("text", "")).strip()
                if title:
                    return title
            if block_type == "section":
                heading = block.get("heading")
                if isinstance(heading, dict):
                    heading_text = str(heading.get("text", "")).strip()
                    if heading_text:
                        return heading_text
                elif isinstance(heading, str) and heading.strip():
                    return heading.strip()

                children_raw = block.get("children", [])
                children = [child for child in children_raw if isinstance(child, dict)]
                nested_title = self._find_first_title(children)
                if nested_title:
                    return nested_title
        return None

    def _resolve_page_count(self, document: NodeOutput) -> int:
        page_count = document.metadata.get("page_count")
        if page_count is not None:
            try:
                return int(page_count)
            except (TypeError, ValueError):
                pass

        blocks = self._get_blocks(document)
        max_page = self._max_page_number(blocks) if blocks else None
        if max_page is not None:
            return max_page
        return 1 if blocks or document.text else 0

    def _max_page_number(self, blocks: list[dict[str, Any]]) -> int | None:
        max_page: int | None = None
        for block in blocks:
            page = self._as_int(block.get("page_number"))
            if page is not None:
                max_page = page if max_page is None else max(page, max_page)

            if str(block.get("type", "")).lower() == "section":
                children_raw = block.get("children", [])
                children = [child for child in children_raw if isinstance(child, dict)]
                section_page = self._max_page_number(children)
                if section_page is not None:
                    max_page = section_page if max_page is None else max(section_page, max_page)

        return max_page

    def _as_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _count_visible_chars(self, text: str) -> int:
        return len("".join(text.split()))

    def _count_words(self, text: str) -> int:
        cjk_chars = len(_CJK_CHAR_RE.findall(text))
        words = len(_WORD_RE.findall(text))
        return cjk_chars + words

    def _average_confidence(self, values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
