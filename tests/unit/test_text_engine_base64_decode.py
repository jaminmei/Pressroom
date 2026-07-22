from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

_ENGINE_ROOT = Path(__file__).resolve().parents[2] / "engines" / "text"


class _DummyHTML2Text:
    def __init__(self) -> None:
        self.ignore_links = False
        self.ignore_images = False
        self.body_width = 0


sys.modules.setdefault("html2text", SimpleNamespace(HTML2Text=_DummyHTML2Text))


def _load_module(name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_engine_mod = _load_module("text_engine_mod_base64_decode", _ENGINE_ROOT / "src" / "text_engine.py")
TextEngine = _engine_mod.TextEngine


def _first_text_block(blocks: list[dict[str, object]]) -> str:
    for block in blocks:
        text = block.get("text")
        if isinstance(text, str):
            return text
    return ""


def test_process_base64_decodes_utf8_payload() -> None:
    engine = TextEngine()
    text = "hello world"
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")

    blocks = engine.process_base64(payload, input_format="text")

    assert _first_text_block(blocks) == text


def test_process_base64_decodes_big5_payload_without_explicit_encoding() -> None:
    engine = TextEngine()
    text = "繁體中文內容"
    payload = base64.b64encode(text.encode("big5")).decode("ascii")

    blocks = engine.process_base64(payload, input_format="text")

    assert _first_text_block(blocks) == text


def test_process_base64_respects_configured_encoding() -> None:
    engine = TextEngine()
    text = "café"
    payload = base64.b64encode(text.encode("cp1252")).decode("ascii")

    blocks = engine.process_base64(payload, input_format="text", config={"encoding": "cp1252"})

    assert _first_text_block(blocks) == text


def test_process_base64_decodes_utf16_payload_with_bom() -> None:
    engine = TextEngine()
    text = "Unicode UTF-16 測試"
    payload = base64.b64encode(text.encode("utf-16")).decode("ascii")

    blocks = engine.process_base64(payload, input_format="text")

    assert _first_text_block(blocks) == text
