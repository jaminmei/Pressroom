from __future__ import annotations

import binascii
import hashlib
import struct
import subprocess
import sys
import zlib
from pathlib import Path

SCRIPT = Path(__file__).with_name("generate-public-fixtures.py")
GENERATED_PATHS = (
    "frontend/e2e/fixtures/test-document.pdf",
    "frontend/e2e/fixtures/test-image.png",
    "frontend/e2e/fixtures/test-single-page.pdf",
    "tests/fixtures/stress/multi-page.pdf",
    "tests/fixtures/stress/single-page.pdf",
    "tests/fixtures/stress/single-page.png",
)


def _run(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _prepare_repo(repo_root: Path) -> tuple[str, str]:
    logo_path = "frontend/public/corgi-logo.png"
    logo_payload = b"independently-managed-logo"
    logo_digest = hashlib.sha256(logo_payload).hexdigest()
    destination = repo_root / logo_path
    destination.parent.mkdir(parents=True)
    destination.write_bytes(logo_payload)
    manifest = repo_root / "scripts/public-binary-assets.txt"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f"{logo_digest}  {logo_path}\n", encoding="utf-8")
    return logo_path, logo_digest


def _parse_png(payload: bytes) -> tuple[int, int, bytes]:
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    position = 8
    width = 0
    height = 0
    compressed = bytearray()
    while position < len(payload):
        chunk_length = struct.unpack(">I", payload[position : position + 4])[0]
        chunk_type = payload[position + 4 : position + 8]
        chunk_data = payload[position + 8 : position + 8 + chunk_length]
        expected_crc = struct.unpack(
            ">I", payload[position + 8 + chunk_length : position + 12 + chunk_length]
        )[0]
        assert binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF == expected_crc
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = (
                struct.unpack(">IIBBBBB", chunk_data)
            )
            assert (bit_depth, color_type, compression, filter_method, interlace) == (
                1,
                0,
                0,
                0,
                0,
            )
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
        position += 12 + chunk_length
    return width, height, zlib.decompress(compressed)


def test_generation_is_deterministic_and_structurally_valid(tmp_path: Path) -> None:
    logo_path, logo_digest = _prepare_repo(tmp_path)

    first_result = _run(tmp_path)
    assert first_result.returncode == 0, first_result.stderr
    first_payloads = {path: (tmp_path / path).read_bytes() for path in GENERATED_PATHS}
    first_manifest = (tmp_path / "scripts/public-binary-assets.txt").read_bytes()

    second_result = _run(tmp_path)
    assert second_result.returncode == 0, second_result.stderr
    assert "already up to date" in second_result.stdout
    assert first_payloads == {path: (tmp_path / path).read_bytes() for path in GENERATED_PATHS}
    assert first_manifest == (tmp_path / "scripts/public-binary-assets.txt").read_bytes()

    manifest_text = first_manifest.decode("utf-8")
    assert f"{logo_digest}  {logo_path}" in manifest_text
    for path, payload in first_payloads.items():
        assert f"{hashlib.sha256(payload).hexdigest()}  {path}" in manifest_text
        if path.endswith(".pdf"):
            assert payload.startswith(b"%PDF-1.4\n")
            assert payload.endswith(b"%%EOF\n")
            expected_pages = 3 if path.endswith("multi-page.pdf") else 1
            assert payload.count(b"/Type /Page ") == expected_pages
            assert b"SYNTHETIC CONTENT" in payload

    e2e_width, e2e_height, e2e_scanlines = _parse_png(
        first_payloads["frontend/e2e/fixtures/test-image.png"]
    )
    assert (e2e_width, e2e_height) == (480, 240)
    assert len(e2e_scanlines) == ((e2e_width + 7) // 8 + 1) * e2e_height
    stress_width, stress_height, stress_scanlines = _parse_png(
        first_payloads["tests/fixtures/stress/single-page.png"]
    )
    assert (stress_width, stress_height) == (640, 320)
    assert len(stress_scanlines) == ((stress_width + 7) // 8 + 1) * stress_height


def test_check_detects_changed_fixture_without_writing(tmp_path: Path) -> None:
    _prepare_repo(tmp_path)
    assert _run(tmp_path).returncode == 0
    fixture = tmp_path / GENERATED_PATHS[0]
    fixture.write_bytes(fixture.read_bytes() + b"changed")
    fixture_before = fixture.read_bytes()
    manifest = tmp_path / "scripts/public-binary-assets.txt"
    manifest_before = manifest.read_bytes()

    result = _run(tmp_path, "--check")

    assert result.returncode == 1
    assert "generated fixture bytes differ" in result.stderr
    assert fixture.read_bytes() == fixture_before
    assert manifest.read_bytes() == manifest_before


def test_check_detects_manifest_mismatch_without_writing(tmp_path: Path) -> None:
    _prepare_repo(tmp_path)
    assert _run(tmp_path).returncode == 0
    manifest = tmp_path / "scripts/public-binary-assets.txt"
    expected = manifest.read_text(encoding="utf-8")
    fixture = tmp_path / GENERATED_PATHS[0]
    fixture_digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    manifest.write_text(expected.replace(fixture_digest, "0" * 64), encoding="utf-8")
    manifest_before = manifest.read_bytes()

    result = _run(tmp_path, "--check")

    assert result.returncode == 1
    assert "generated fixture manifest mismatch" in result.stderr
    assert manifest.read_bytes() == manifest_before


def test_check_rejects_an_eighth_binary_manifest_entry(tmp_path: Path) -> None:
    _prepare_repo(tmp_path)
    assert _run(tmp_path).returncode == 0
    manifest = tmp_path / "scripts/public-binary-assets.txt"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + f"{'0' * 64}  tests/fixtures/unapproved.bin\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, "--check")

    assert result.returncode == 1
    assert "unexpected binary manifest path: tests/fixtures/unapproved.bin" in result.stderr
