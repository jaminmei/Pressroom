from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from app.models.execution import NodeOutput
from app.models.output import OutputMetadata, OutputResult
from app.services.output_formatter.base import FormatterContext, OutputFormatter
from app.services.output_formatter.stats import collect_block_stats, weighted_confidence


@dataclass
class _RenderState:
    current_page: int | None = None
    has_visible_output: bool = False


@dataclass
class _Stats:
    char_count: int = 0
    word_count: int = 0
    confidence_pairs: list[tuple[float, int]] = field(default_factory=list)


class MarkdownFormatter(OutputFormatter):
    """Render NodeOutput into Markdown text with YAML front matter."""

    def format(
        self,
        document: NodeOutput,
        config: dict,
        context: FormatterContext,
    ) -> OutputResult:
        start = perf_counter()
        include_metadata = bool(config.get("include_metadata", False))

        state = _RenderState()
        stats = _Stats()

        # Determine blocks: prefer structured blocks, fall back to text
        blocks = self._get_blocks(document)
        if blocks:
            body = self._render_blocks(blocks, state, stats, "")
        else:
            body = document.text or ""

        title = self._resolve_title(document, context.source_filename)
        confidence = weighted_confidence(stats.confidence_pairs)

        doc_meta = document.metadata
        front_matter: dict[str, Any] = {
            "title": title,
            "source": context.source_filename,
            "engine_chain": context.engine_chain or doc_meta.get("engine_chain", []),
            "created_at": doc_meta.get("created_at") or self._now_iso(),
            "page_count": self._resolve_page_count(document),
        }

        if include_metadata:
            front_matter.update(
                {
                    "char_count": stats.char_count,
                    "word_count": stats.word_count,
                    "confidence": confidence,
                    "language": doc_meta.get("language"),
                }
            )

        front_matter_yaml = yaml.safe_dump(
            front_matter,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()
        text = f"---\n{front_matter_yaml}\n---\n\n{body}"

        metadata = OutputMetadata(
            processing_time_ms=max(int((perf_counter() - start) * 1000), 0),
            page_count=front_matter["page_count"],
            char_count=stats.char_count,
            word_count=stats.word_count,
            confidence=confidence,
            engine_chain=context.engine_chain or doc_meta.get("engine_chain", []),
            source_filename=context.source_filename,
        )

        return OutputResult(
            format="markdown",
            content_type="text/markdown",
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

    def _render_blocks(
        self,
        blocks: list[dict[str, Any]],
        state: _RenderState,
        stats: _Stats,
        output: str,
    ) -> str:
        for block in blocks:
            block_type = str(block.get("type", "")).lower()

            if block_type in {"header", "footer"}:
                continue

            if block_type == "section":
                output = self._render_section(block, state, stats, output)
                continue

            page_number = self._as_int(block.get("page_number"))
            if (
                state.has_visible_output
                and page_number is not None
                and state.current_page is not None
                and page_number != state.current_page
            ):
                output = output.rstrip() + "\n\n---\n\n"

            chunk = self._render_leaf(block)
            if not chunk:
                continue

            output = self._append_chunk(output, chunk)
            state.has_visible_output = True
            if page_number is not None:
                state.current_page = page_number

            self._collect_stats(block, stats)

        return output

    def _render_section(
        self,
        block: dict[str, Any],
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
            output = self._render_blocks([heading_block], state, stats, output)

        children_raw = block.get("children", [])
        children = [child for child in children_raw if isinstance(child, dict)]
        return self._render_blocks(children, state, stats, output)

    def _render_leaf(self, block: dict[str, Any]) -> str:
        block_type = str(block.get("type", "")).lower()

        if block_type == "title":
            text = str(block.get("text", "")).strip()
            if not text:
                return ""
            level = self._as_int(block.get("level")) or 1
            level = min(max(level, 1), 6)
            return f"{'#' * level} {text}"

        if block_type == "paragraph":
            return str(block.get("text", "")).strip()

        if block_type == "list":
            return self._render_list(block)

        if block_type == "table":
            return self._render_table(block)

        if block_type == "figure":
            return self._render_figure(block)

        if block_type == "code":
            return self._render_code(block)

        if block_type == "footnote":
            marker = str(block.get("marker", "")).strip()
            text = str(block.get("text", "")).strip()
            if not marker or not text:
                return ""
            return f"[^{marker}]: {text}"

        if block_type == "field":
            field_name = str(block.get("field_name", "")).strip()
            text = str(block.get("text", "")).strip()
            if not text:
                return ""
            if field_name:
                # Format as key-value pair with bold key
                return f"**{field_name}:** {text}"
            return text

        return str(block.get("text", "")).strip()

    def _render_list(self, block: dict[str, Any]) -> str:
        list_type = str(block.get("list_type", "unordered")).lower()
        ordered = list_type == "ordered"

        items_raw = block.get("items", [])
        items = [item for item in items_raw if isinstance(item, (dict, str))]

        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            lines.extend(self._render_list_item(item, ordered=ordered, level=0, index=index))

        return "\n".join(line for line in lines if line.strip())

    def _render_list_item(
        self,
        item: dict[str, Any] | str,
        *,
        ordered: bool,
        level: int,
        index: int,
    ) -> list[str]:
        if isinstance(item, str):
            item_dict: dict[str, Any] = {"text": item}
        else:
            item_dict = item

        indent_unit = "   " if ordered else "  "
        marker = f"{index}. " if ordered else "- "

        text = str(item_dict.get("text", "")).strip()
        line = f"{indent_unit * level}{marker}{text}".rstrip()
        lines = [line]

        children_raw = item_dict.get("children", [])
        children = [child for child in children_raw if isinstance(child, (dict, str))]
        for child_index, child in enumerate(children, start=1):
            child_ordered = ordered
            if isinstance(child, dict) and "list_type" in child:
                child_ordered = str(child["list_type"]).lower() == "ordered"
            lines.extend(
                self._render_list_item(
                    child,
                    ordered=child_ordered,
                    level=level + 1,
                    index=child_index,
                )
            )

        return lines

    def _render_table(self, block: dict[str, Any]) -> str:
        headers = self._to_row_strings(block.get("headers", []))
        rows = self._to_rows(block.get("rows", []))

        if not headers and rows:
            headers = rows[0]
            rows = rows[1:]

        if not headers:
            return ""

        header_row = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"

        table_lines = [header_row, separator]
        table_lines.extend("| " + " | ".join(row) + " |" for row in rows)

        caption = str(block.get("caption", "")).strip()
        if caption:
            table_lines.append(f"*{caption}*")

        return "\n".join(table_lines)

    def _render_figure(self, block: dict[str, Any]) -> str:
        image_ref = block.get("image_ref")
        path: str = ""
        if isinstance(image_ref, dict):
            path = str(image_ref.get("path", ""))
        elif isinstance(image_ref, str):
            path = image_ref

        filename = Path(path).name if path else ""
        image_path = f"./images/{filename}" if filename else ""

        caption = str(block.get("caption", "")).strip()
        alt_text = str(block.get("alt_text", "")).strip() or caption
        figure_lines = [f"![{alt_text}]({image_path})"]

        if caption:
            figure_lines.append(f"*{caption}*")

        return "\n".join(figure_lines)

    def _render_code(self, block: dict[str, Any]) -> str:
        language = str(block.get("language", "")).strip()
        code_text = str(block.get("code", block.get("text", ""))).strip("\n")

        if language:
            return f"```{language}\n{code_text}\n```"
        return f"```\n{code_text}\n```"

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

        if output.endswith("\n\n---\n\n"):
            return output + chunk

        return output + "\n\n" + chunk

    def _collect_stats(self, block: dict[str, Any], stats: _Stats) -> None:
        visible_text = self._extract_visible_text(block)
        char_count, word_count, confidence_pair = collect_block_stats(block, visible_text)
        stats.char_count += char_count
        stats.word_count += word_count
        if confidence_pair is not None:
            stats.confidence_pairs.append(confidence_pair)

    def _extract_visible_text(self, block: dict[str, Any]) -> str:
        block_type = str(block.get("type", "")).lower()

        if block_type in {"title", "paragraph", "footnote"}:
            if block_type == "footnote":
                marker = str(block.get("marker", "")).strip()
                text = str(block.get("text", "")).strip()
                return f"{marker} {text}".strip()
            return str(block.get("text", "")).strip()

        if block_type == "field":
            field_name = str(block.get("field_name", "")).strip()
            text = str(block.get("text", "")).strip()
            if field_name and text:
                return f"{field_name}: {text}"
            return text

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

        return str(block.get("text", "")).strip()

    def _extract_list_texts(self, items_raw: Any) -> list[str]:
        if not isinstance(items_raw, list):
            return []

        texts: list[str] = []
        for item in items_raw:
            if isinstance(item, str):
                item_text = item.strip()
                if item_text:
                    texts.append(item_text)
                continue
            if not isinstance(item, dict):
                continue

            item_text = str(item.get("text", "")).strip()
            if item_text:
                texts.append(item_text)
            texts.extend(self._extract_list_texts(item.get("children", [])))

        return texts

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

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
