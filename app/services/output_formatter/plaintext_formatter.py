from __future__ import annotations

import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.models.execution import NodeOutput
from app.models.output import OutputMetadata, OutputResult
from app.services.output_formatter.base import FormatterContext, OutputFormatter

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


@dataclass
class _RenderState:
    current_page: int | None = None
    has_visible_output: bool = False


@dataclass
class _Stats:
    char_count: int = 0
    word_count: int = 0
    confidence_values: list[float] = field(default_factory=list)


class PlainTextFormatter(OutputFormatter):
    """Render NodeOutput to plain text."""

    def format(
        self,
        document: NodeOutput,
        config: dict,
        context: FormatterContext,
    ) -> OutputResult:
        start = perf_counter()
        preserve_structure = bool(config.get("preserve_structure", True))

        state = _RenderState()
        stats = _Stats()

        # Determine blocks: prefer structured blocks, fall back to text
        blocks = self._get_blocks(document)
        if blocks:
            body = self._render_blocks(blocks, preserve_structure, state, stats, "")
        else:
            body = document.text or ""

        metadata = OutputMetadata(
            processing_time_ms=max(int((perf_counter() - start) * 1000), 0),
            page_count=self._resolve_page_count(document),
            char_count=stats.char_count,
            word_count=stats.word_count,
            confidence=self._average_confidence(stats.confidence_values),
            engine_chain=context.engine_chain or document.metadata.get("engine_chain", []),
            source_filename=context.source_filename,
        )

        return OutputResult(
            format="text",
            content_type="text/plain; charset=utf-8",
            text=body,
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

    def _render_blocks(
        self,
        blocks: list[dict[str, Any]],
        preserve_structure: bool,
        state: _RenderState,
        stats: _Stats,
        output: str,
    ) -> str:
        for block in blocks:
            block_type = str(block.get("type", "")).lower()

            if block_type in {"header", "footer"}:
                continue

            if block_type == "section":
                output = self._render_section(block, preserve_structure, state, stats, output)
                continue

            page_number = self._as_int(block.get("page_number"))
            if (
                preserve_structure
                and state.has_visible_output
                and page_number is not None
                and state.current_page is not None
                and page_number != state.current_page
            ):
                output = output.rstrip() + f"\n\n========== Page {page_number} ==========\n\n"

            chunk = self._render_leaf(block, preserve_structure)
            if not chunk:
                continue

            output = self._append_chunk(output, chunk)
            state.has_visible_output = True
            if page_number is not None:
                state.current_page = page_number

            self._collect_stats(block, preserve_structure, stats)

        return output

    def _render_section(
        self,
        block: dict[str, Any],
        preserve_structure: bool,
        state: _RenderState,
        stats: _Stats,
        output: str,
    ) -> str:
        heading = block.get("heading")
        heading_block: dict[str, Any] | None = None

        if isinstance(heading, dict):
            heading_text = str(heading.get("text", "")).strip()
            if heading_text:
                heading_block = {
                    "type": "title",
                    "text": heading_text,
                    "level": heading.get("level", 2),
                    "page_number": heading.get("page_number", block.get("page_number")),
                    "confidence": heading.get("confidence", block.get("confidence")),
                }
        elif isinstance(heading, str) and heading.strip():
            heading_block = {
                "type": "title",
                "text": heading.strip(),
                "level": self._as_int(block.get("level")) or 2,
                "page_number": block.get("page_number"),
                "confidence": block.get("confidence"),
            }

        if heading_block is not None:
            output = self._render_blocks([heading_block], preserve_structure, state, stats, output)

        children_raw = block.get("children", [])
        children = [child for child in children_raw if isinstance(child, dict)]
        return self._render_blocks(children, preserve_structure, state, stats, output)

    def _render_leaf(self, block: dict[str, Any], preserve_structure: bool) -> str:
        block_type = str(block.get("type", "")).lower()

        if block_type == "title":
            text = str(block.get("text", "")).strip()
            if not text:
                return ""
            return f"=== {text} ===" if preserve_structure else text

        if block_type == "paragraph":
            return str(block.get("text", "")).strip()

        if block_type == "list":
            return self._render_list(block, preserve_structure)

        if block_type == "table":
            return self._render_table(block, preserve_structure)

        if block_type == "figure":
            if not preserve_structure:
                return ""
            caption = str(block.get("caption", "")).strip()
            alt_text = str(block.get("alt_text", "")).strip()
            label = caption or alt_text
            return f"[圖片: {label}]"

        if block_type == "code":
            return str(block.get("code", block.get("text", ""))).strip()

        if block_type == "footnote":
            marker = str(block.get("marker", "")).strip()
            text = str(block.get("text", "")).strip()
            if not text:
                return ""
            if preserve_structure:
                return f"[註: {marker}] {text}" if marker else text
            return text

        if block_type == "field":
            field_name = str(block.get("field_name", "")).strip()
            text = str(block.get("text", "")).strip()
            if not text:
                return ""
            if field_name:
                return f"{field_name}: {text}"
            return text

        return str(block.get("text", "")).strip()

    def _render_list(self, block: dict[str, Any], preserve_structure: bool) -> str:
        items_raw = block.get("items", [])
        items = [item for item in items_raw if isinstance(item, (dict, str))]

        lines: list[str] = []
        for item in items:
            lines.extend(
                self._render_list_item(item, preserve_structure=preserve_structure, level=0)
            )

        return "\n".join(line for line in lines if line.strip())

    def _render_list_item(
        self,
        item: dict[str, Any] | str,
        *,
        preserve_structure: bool,
        level: int,
    ) -> list[str]:
        if isinstance(item, str):
            item_dict: dict[str, Any] = {"text": item}
        else:
            item_dict = item

        text = str(item_dict.get("text", "")).strip()
        if not text:
            lines: list[str] = []
        elif preserve_structure:
            lines = [f"{'  ' * level}- {text}"]
        else:
            lines = [text]

        children_raw = item_dict.get("children", [])
        children = [child for child in children_raw if isinstance(child, (dict, str))]
        for child in children:
            lines.extend(
                self._render_list_item(
                    child,
                    preserve_structure=preserve_structure,
                    level=level + 1,
                )
            )

        return lines

    def _render_table(self, block: dict[str, Any], preserve_structure: bool) -> str:
        headers = self._to_row_strings(block.get("headers", []))
        rows = self._to_rows(block.get("rows", []))

        if not headers and rows:
            headers = rows[0]
            rows = rows[1:]

        if not headers:
            return ""

        if not preserve_structure:
            csv_lines = [",".join(headers)]
            csv_lines.extend(",".join(row) for row in rows)
            return "\n".join(csv_lines)

        widths = [len(cell) for cell in headers]
        for row in rows:
            for index, cell in enumerate(row):
                if index < len(widths):
                    widths[index] = max(widths[index], len(cell))

        def pad(cells: list[str]) -> str:
            padded = [cells[i].ljust(widths[i]) for i in range(len(widths))]
            return " | ".join(padded)

        header_row = pad(headers)
        separator = "-|-".join("-" * width for width in widths)
        body_rows = [pad(row) for row in rows]

        lines = ["[表格]", header_row, separator, *body_rows]
        caption = str(block.get("caption", "")).strip()
        if caption:
            lines.append(f"({caption})")

        return "\n".join(lines)

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

    def _append_chunk(self, output: str, chunk: str) -> str:
        chunk = chunk.strip("\n")
        if not chunk:
            return output

        if not output:
            return chunk

        if output.endswith("\n\n"):
            return output + chunk

        return output + "\n\n" + chunk

    def _collect_stats(
        self, block: dict[str, Any], preserve_structure: bool, stats: _Stats
    ) -> None:
        visible_text = self._extract_visible_text(block, preserve_structure)
        if visible_text:
            stats.char_count += self._count_visible_chars(visible_text)
            stats.word_count += self._count_words(visible_text)

        confidence = block.get("confidence")
        if isinstance(confidence, (int, float)) and visible_text:
            stats.confidence_values.append(float(confidence))

    def _extract_visible_text(self, block: dict[str, Any], preserve_structure: bool) -> str:
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
            if not preserve_structure:
                return " ".join(part for part in [headers, rows] if part).strip()
            return " ".join(part for part in [headers, rows, caption] if part).strip()

        if block_type == "figure":
            if not preserve_structure:
                return ""
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
