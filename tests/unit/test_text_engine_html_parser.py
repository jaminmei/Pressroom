from __future__ import annotations

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


_engine_mod = _load_module("text_engine_mod_html_parser", _ENGINE_ROOT / "src" / "text_engine.py")
TextEngine = _engine_mod.TextEngine


def _paragraph_texts(blocks: list[dict[str, object]]) -> list[str]:
    return [
        str(block.get("text", ""))
        for block in blocks
        if block.get("type") == "paragraph" and isinstance(block.get("text"), str)
    ]


def test_process_html_keeps_multiple_article_contents() -> None:
    engine = TextEngine()
    html = """
    <html><body>
      <article><p>First article paragraph.</p></article>
      <article><p>Second article paragraph.</p></article>
    </body></html>
    """

    blocks = engine.process_html(html)
    paragraphs = _paragraph_texts(blocks)

    assert "First article paragraph." in paragraphs
    assert "Second article paragraph." in paragraphs


def test_process_html_keeps_content_outside_main_or_article() -> None:
    engine = TextEngine()
    html = """
    <html><body>
      <p>Body intro paragraph.</p>
      <main><p>Main area paragraph.</p></main>
      <section><p>Outside semantic root paragraph.</p></section>
    </body></html>
    """

    blocks = engine.process_html(html)
    paragraphs = _paragraph_texts(blocks)

    assert "Body intro paragraph." in paragraphs
    assert "Main area paragraph." in paragraphs
    assert "Outside semantic root paragraph." in paragraphs


def test_process_html_keeps_existing_dedup_behavior() -> None:
    engine = TextEngine()
    html = """
    <html><body>
      <main><p>Duplicated paragraph.</p></main>
      <article><p>Duplicated paragraph.</p></article>
      <p>Duplicated paragraph.</p>
    </body></html>
    """

    blocks = engine.process_html(html)
    paragraphs = _paragraph_texts(blocks)

    assert paragraphs.count("Duplicated paragraph.") == 1
