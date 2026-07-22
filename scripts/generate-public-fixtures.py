#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jamin Mei and ricoyudog
# SPDX-License-Identifier: MIT
"""Generate the public repository's six synthetic binary test fixtures.

The implementation uses only the Python standard library. PDF files use the
built-in PDF Helvetica font, while PNG files use a small bitmap font encoded
below. No system fonts, timestamps, random values, network access, or external
tools influence the output.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("scripts/public-binary-assets.txt")
MANIFEST_HEADER = (
    "# SHA256 and path for each binary asset approved for public distribution.\n"
    "# Synthetic fixture entries are maintained by scripts/generate-public-fixtures.py.\n"
)
MANUALLY_MAINTAINED_ASSETS = ("frontend/public/corgi-logo.png",)

# Five-bit-wide, seven-row glyphs. Each integer is one row, most-significant
# pixel first. The glyphs are original project test data distributed under MIT.
FONT_5X7: dict[str, tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x14, 0x04, 0x04, 0x04, 0x1F),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E),
    "6": (0x0E, 0x10, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x0E),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
}


class FixtureError(Exception):
    """Raised when fixture or manifest validation cannot continue."""


def _escape_pdf_text(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("ascii")


def _make_pdf(pages: tuple[tuple[str, ...], ...]) -> bytes:
    """Build a PDF 1.4 document with deterministic object order and offsets."""
    font_object = 3 + 2 * len(pages)
    page_objects = [3 + 2 * index for index in range(len(pages))]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{number} 0 R".encode("ascii") for number in page_objects)
            + f"] /Count {len(pages)} >>".encode("ascii")
        ),
    ]

    for page_index, lines in enumerate(pages):
        page_object = page_objects[page_index]
        content_object = page_object + 1
        commands = [b"BT", b"/F1 18 Tf", b"54 720 Td"]
        for line_index, line in enumerate(lines):
            if line_index:
                commands.append(b"0 -30 Td")
            commands.append(b"(" + _escape_pdf_text(line) + b") Tj")
        commands.append(b"ET")
        stream = b"\n".join(commands) + b"\n"
        objects.extend(
            [
                (
                    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    + f"/Resources << /Font << /F1 {font_object} 0 R >> >> ".encode("ascii")
                    + f"/Contents {content_object} 0 R >>".encode("ascii")
                ),
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream",
            ]
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(payload)
        document.extend(b"\nendobj\n")

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def _adler32(payload: bytes) -> int:
    modulus = 65521
    first = 1
    second = 0
    for byte in payload:
        first = (first + byte) % modulus
        second = (second + first) % modulus
    return (second << 16) | first


def _stored_zlib(payload: bytes) -> bytes:
    """Encode zlib data with DEFLATE stored blocks, independent of zlib versions."""
    encoded = bytearray(b"\x78\x01")
    position = 0
    while position < len(payload):
        block = payload[position : position + 65535]
        position += len(block)
        encoded.append(0x01 if position == len(payload) else 0x00)
        encoded.extend(struct.pack("<HH", len(block), len(block) ^ 0xFFFF))
        encoded.extend(block)
    encoded.extend(struct.pack(">I", _adler32(payload)))
    return bytes(encoded)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _make_png(
    width: int,
    height: int,
    lines: tuple[tuple[int, int, int, str], ...],
) -> bytes:
    """Build a 1-bit grayscale PNG containing fixed bitmap-font text."""
    row_bytes = (width + 7) // 8
    pixels = bytearray(b"\xff" * (row_bytes * height))

    def set_black(x: int, y: int) -> None:
        if not 0 <= x < width or not 0 <= y < height:
            raise FixtureError(f"bitmap glyph exceeds {width}x{height} canvas")
        offset = y * row_bytes + x // 8
        pixels[offset] &= ~(1 << (7 - x % 8))

    for x_origin, y_origin, scale, text in lines:
        cursor = x_origin
        for character in text:
            try:
                glyph = FONT_5X7[character]
            except KeyError as exc:
                raise FixtureError(f"unsupported bitmap character: {character!r}") from exc
            for row_index, row_bits in enumerate(glyph):
                for column in range(5):
                    if row_bits & (1 << (4 - column)):
                        for y_repeat in range(scale):
                            for x_repeat in range(scale):
                                set_black(
                                    cursor + column * scale + x_repeat,
                                    y_origin + row_index * scale + y_repeat,
                                )
            cursor += 6 * scale

    scanlines = b"".join(
        b"\x00" + pixels[row * row_bytes : (row + 1) * row_bytes] for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", _stored_zlib(scanlines))
        + _png_chunk(b"IEND", b"")
    )


def build_fixtures() -> dict[str, bytes]:
    """Return every generated fixture as repository-relative path and bytes."""
    return {
        "frontend/e2e/fixtures/test-document.pdf": _make_pdf(
            (("PUBLIC E2E DOCUMENT", "SYNTHETIC CONTENT", "NO PERSONAL DATA"),)
        ),
        "frontend/e2e/fixtures/test-image.png": _make_png(
            480,
            240,
            (
                (24, 28, 3, "SYNTHETIC OCR TEST"),
                (24, 82, 3, "DOCUMENT CONVERSION"),
                (24, 136, 3, "PUBLIC FIXTURE 0.2.0"),
            ),
        ),
        "frontend/e2e/fixtures/test-single-page.pdf": _make_pdf(
            (("PUBLIC E2E SINGLE PAGE", "SYNTHETIC CONTENT", "NO PERSONAL DATA"),)
        ),
        "tests/fixtures/stress/multi-page.pdf": _make_pdf(
            tuple(
                (
                    f"STRESS FIXTURE PAGE {page_number}",
                    "SYNTHETIC CONTENT",
                    "NO PERSONAL DATA",
                )
                for page_number in range(1, 4)
            )
        ),
        "tests/fixtures/stress/single-page.pdf": _make_pdf(
            (("STRESS SINGLE PAGE", "SYNTHETIC CONTENT", "NO PERSONAL DATA"),)
        ),
        "tests/fixtures/stress/single-page.png": _make_png(
            640,
            320,
            (
                (32, 36, 4, "OCR STRESS FIXTURE"),
                (32, 108, 4, "SYNTHETIC CONTENT"),
                (32, 180, 4, "PUBLIC TEST DATA"),
            ),
        ),
    }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digest, separator, relative_path = line.partition("  ")
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
            or not relative_path
        ):
            raise FixtureError(f"invalid manifest entry at {path}:{line_number}")
        if relative_path in entries:
            raise FixtureError(f"duplicate manifest path at {path}:{line_number}: {relative_path}")
        entries[relative_path] = digest.lower()
    return entries


def _render_manifest(entries: dict[str, str]) -> str:
    body = "".join(f"{digest}  {path}\n" for path, digest in sorted(entries.items()))
    return MANIFEST_HEADER + body


def _manual_asset_errors(repo_root: Path, entries: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for relative_path in MANUALLY_MAINTAINED_ASSETS:
        expected_digest = entries.get(relative_path)
        if expected_digest is None:
            errors.append(f"manually maintained asset is missing from manifest: {relative_path}")
            continue
        asset_path = repo_root / relative_path
        if not asset_path.is_file():
            errors.append(f"manually maintained asset is missing: {relative_path}")
            continue
        actual_digest = _sha256(asset_path.read_bytes())
        if actual_digest != expected_digest:
            errors.append(
                f"manually maintained asset manifest mismatch: {relative_path} "
                f"(expected {expected_digest}, got {actual_digest})"
            )
    return errors


def _unexpected_manifest_paths(entries: dict[str, str], generated: dict[str, bytes]) -> list[str]:
    approved_paths = set(generated) | set(MANUALLY_MAINTAINED_ASSETS)
    return sorted(set(entries) - approved_paths)


def write_repository(repo_root: Path) -> list[str]:
    """Write generated fixtures and refresh their entries in the binary manifest."""
    generated = build_fixtures()
    manifest = repo_root / MANIFEST_PATH
    entries = _load_manifest(manifest)
    manual_errors = _manual_asset_errors(repo_root, entries)
    unexpected_paths = _unexpected_manifest_paths(entries, generated)
    if manual_errors or unexpected_paths:
        details = manual_errors + [
            f"unexpected binary manifest path: {path}" for path in unexpected_paths
        ]
        raise FixtureError("; ".join(details))

    changed: list[str] = []
    for relative_path, expected_bytes in generated.items():
        destination = repo_root / relative_path
        if not destination.exists() or destination.read_bytes() != expected_bytes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(expected_bytes)
            changed.append(relative_path)

    entries.update({path: _sha256(payload) for path, payload in generated.items()})
    rendered = _render_manifest(entries).encode("utf-8")
    if not manifest.exists() or manifest.read_bytes() != rendered:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(rendered)
        changed.append(MANIFEST_PATH.as_posix())
    return changed


def check_repository(repo_root: Path) -> list[str]:
    """Return validation errors without modifying fixtures or their manifest."""
    generated = build_fixtures()
    manifest_path = repo_root / MANIFEST_PATH
    try:
        entries = _load_manifest(manifest_path)
    except (FixtureError, OSError, UnicodeError) as exc:
        return [str(exc)]
    if not manifest_path.exists():
        return [f"binary manifest is missing: {MANIFEST_PATH.as_posix()}"]

    errors = _manual_asset_errors(repo_root, entries)
    errors.extend(
        f"unexpected binary manifest path: {path}"
        for path in _unexpected_manifest_paths(entries, generated)
    )
    for relative_path, expected_bytes in generated.items():
        expected_digest = _sha256(expected_bytes)
        fixture_path = repo_root / relative_path
        if not fixture_path.is_file():
            errors.append(f"generated fixture is missing: {relative_path}")
        else:
            actual_bytes = fixture_path.read_bytes()
            if actual_bytes != expected_bytes:
                errors.append(
                    f"generated fixture bytes differ: {relative_path} "
                    f"(expected {expected_digest}, got {_sha256(actual_bytes)})"
                )
        manifest_digest = entries.get(relative_path)
        if manifest_digest != expected_digest:
            errors.append(
                f"generated fixture manifest mismatch: {relative_path} "
                f"(expected {expected_digest}, got {manifest_digest or 'missing'})"
            )
    return errors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify fixture bytes and manifest hashes without modifying files",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.check:
            errors = check_repository(args.repo_root)
            if errors:
                for error in errors:
                    print(f"fixture check failed: {error}", file=sys.stderr)
                return 1
            print("Public fixture bytes and manifest hashes are reproducible.")
            return 0

        changed = write_repository(args.repo_root)
    except (FixtureError, OSError, UnicodeError) as exc:
        print(f"fixture generation failed: {exc}", file=sys.stderr)
        return 1
    if changed:
        print("Updated public fixtures: " + ", ".join(changed))
    else:
        print("Public fixtures are already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
