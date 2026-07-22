from __future__ import annotations

import re
from typing import Literal, Protocol, TypeAlias, cast

from app.models.inputs import TextContent, TextInput, TextSource
from app.storage.base import StorageAdapter

TextEncoding: TypeAlias = Literal["utf-8", "ascii", "big5", "gb2312", "gbk", "utf-16"]


class _ChardetModule(Protocol):
    def detect(self, byte_string: bytes) -> dict[str, object]: ...


chardet: _ChardetModule | None
try:
    import chardet as _chardet
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    chardet = None
else:
    chardet = cast(_ChardetModule, _chardet)


class HtmlValidationError(ValueError):
    """Raised when HTML preprocessing fails validation."""


class HtmlPreprocessor:
    """Decode and clean HTML uploads into TextInput payloads."""

    MAX_HTML_SIZE_BYTES = 10 * 1024 * 1024
    HTML_MIME = "text/html"
    _ENCODING_CANDIDATES: tuple[TextEncoding, ...] = (
        "utf-8",
        "utf-16",
        "big5",
        "gbk",
        "gb2312",
        "ascii",
    )

    async def preprocess(
        self,
        *,
        file_path: str,
        filename: str,
        storage: StorageAdapter,
    ) -> TextInput:
        raw_bytes = await storage.read_file(file_path)
        raw_html, encoding = self._decode_html(raw_bytes)
        cleaned_html = self.clean_html(raw_html)

        return TextInput(
            source=TextSource(
                type="html_extract",
                original_filename=filename,
                original_mime_type=self.HTML_MIME,
                encoding=self._normalize_encoding_for_model(encoding),
            ),
            content=TextContent(
                raw=cleaned_html,
                char_count=len(cleaned_html),
                line_count=len(cleaned_html.splitlines()),
            ),
        )

    def _decode_html(self, raw_bytes: bytes) -> tuple[str, TextEncoding]:
        if not raw_bytes:
            raise HtmlValidationError("HTML file is empty")
        if len(raw_bytes) > self.MAX_HTML_SIZE_BYTES:
            raise HtmlValidationError("HTML file exceeds max size")

        encoding = self.detect_encoding(raw_bytes)
        decoded = raw_bytes.decode(encoding, errors="replace")
        decoded = decoded.lstrip("\ufeff")
        return decoded, encoding

    def detect_encoding(self, raw_bytes: bytes) -> TextEncoding:
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return "utf-8"
        if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
            return "utf-16"

        if chardet is not None:
            detected = chardet.detect(raw_bytes).get("encoding")
            guess = detected if isinstance(detected, str) else None
            normalized_guess = self._normalize_detected_encoding(guess)
            if normalized_guess is not None:
                return normalized_guess

        for encoding in self._ENCODING_CANDIDATES:
            try:
                raw_bytes.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue

        return "utf-8"

    def clean_html(self, html: str) -> str:
        cleaned = re.sub(
            r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
            "",
            html,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _normalize_detected_encoding(self, encoding: str | None) -> TextEncoding | None:
        if not encoding:
            return None
        normalized = encoding.lower().replace("_", "-")
        mapping: dict[str, TextEncoding] = {
            "utf-8-sig": "utf-8",
            "utf-16le": "utf-16",
            "utf-16be": "utf-16",
            "cp950": "big5",
            "big5hkscs": "big5",
            "gb18030": "gbk",
        }
        normalized = mapping.get(normalized, normalized)
        if normalized in self._ENCODING_CANDIDATES:
            return normalized
        return None

    def _normalize_encoding_for_model(self, encoding: str) -> TextEncoding:
        if encoding in self._ENCODING_CANDIDATES:
            return encoding
        return "utf-8"
