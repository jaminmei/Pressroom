#!/usr/bin/env python3
"""Validate the MIT/GPL license boundary of the public source tree."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_ENGINE_RELATIVE = Path("engines/text")
SPDX_IDENTIFIER = "SPDX-License-Identifier: GPL-3.0-only"
GPL_DEPENDENCY = "html2text"
GPL_DEPENDENCY_VERSION = "2020.1.16"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_license_documents(repo_root: Path) -> list[str]:
    errors: list[str] = []
    mit_license = _read(repo_root / "LICENSE")
    if mit_license is None or "MIT License" not in mit_license:
        errors.append("root LICENSE must contain the MIT license")
    elif not all(name in mit_license for name in ("Jamin Mei", "ricoyudog")):
        errors.append("root LICENSE must contain both approved copyright holders")

    canonical_gpl = _read(repo_root / "LICENSES/GPL-3.0-only.txt")
    engine_gpl = _read(repo_root / TEXT_ENGINE_RELATIVE / "COPYING")
    if canonical_gpl is None or engine_gpl is None:
        errors.append("both canonical and Text engine GPL license copies are required")
    elif canonical_gpl != engine_gpl:
        errors.append("Text engine GPL license copy must match the canonical license text")
    elif "GNU GENERAL PUBLIC LICENSE" not in canonical_gpl or "Version 3" not in canonical_gpl:
        errors.append("GPL-3.0-only license files do not contain the expected license text")

    root_readme = _read(repo_root / "README.md") or ""
    notices = _read(repo_root / "THIRD_PARTY_NOTICES.md") or ""
    text_readme = _read(repo_root / TEXT_ENGINE_RELATIVE / "README.md") or ""
    if "engines/text/**" not in root_readme or "GPL-3.0-only" not in root_readme:
        errors.append("root README must describe the Text engine GPL scope")
    expected_dependency = f"{GPL_DEPENDENCY}=={GPL_DEPENDENCY_VERSION}"
    if expected_dependency not in notices or "GPL-3.0-only" not in notices:
        errors.append("third-party notices must document the pinned GPL dependency")
    if "engines/text/**" not in text_readme or "GPL-3.0-only" not in text_readme:
        errors.append("Text engine README must describe its GPL scope")
    return errors


def _check_text_engine_spdx(repo_root: Path) -> list[str]:
    errors: list[str] = []
    engine_root = repo_root / TEXT_ENGINE_RELATIVE
    if not engine_root.is_dir():
        return ["Text engine directory is missing"]
    for path in sorted(engine_root.rglob("*")):
        if (
            not path.is_file()
            or path.name == "COPYING"
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        text = _read(path)
        relative = path.relative_to(repo_root).as_posix()
        if text is None:
            errors.append(f"Text engine source is not UTF-8 text: {relative}")
            continue
        header = "\n".join(text.splitlines()[:5])
        if SPDX_IDENTIFIER not in header:
            errors.append(f"Text engine file lacks the GPL SPDX header: {relative}")
    return errors


def _imported_modules(path: Path) -> tuple[set[str], str | None]:
    text = _read(path)
    if text is None:
        return set(), "file is not readable UTF-8 Python"
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return set(), "file is not valid Python"
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules, None


def _check_service_boundary(repo_root: Path) -> list[str]:
    errors: list[str] = []
    source_roots = [repo_root / "app"]
    engines_root = repo_root / "engines"
    if engines_root.is_dir():
        source_roots.extend(
            path for path in engines_root.iterdir() if path.is_dir() and path.name != "text"
        )
    for source_root in source_roots:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            modules, parse_error = _imported_modules(path)
            relative = path.relative_to(repo_root).as_posix()
            if parse_error:
                errors.append(f"cannot inspect Python imports in {relative}: {parse_error}")
                continue
            if any(
                module == GPL_DEPENDENCY
                or module.startswith(f"{GPL_DEPENDENCY}.")
                or module == "engines.text"
                or module.startswith("engines.text.")
                for module in modules
            ):
                errors.append(f"GPL Text engine import crosses the service boundary: {relative}")

    requirement_pattern = re.compile(
        rf"^\s*{re.escape(GPL_DEPENDENCY)}(?:\s|[<>=!~]|$)",
        re.MULTILINE,
    )
    requirement_paths = list(repo_root.glob("requirements*.txt"))
    requirement_paths.extend(repo_root.glob("requirements*.lock"))
    requirement_paths.extend(engines_root.glob("*/requirements*.txt"))
    requirement_paths.extend(engines_root.glob("*/requirements*.lock"))
    for path in sorted(requirement_paths):
        if TEXT_ENGINE_RELATIVE in path.relative_to(repo_root).parents:
            continue
        text = _read(path) or ""
        if requirement_pattern.search(text):
            errors.append(
                "GPL Text engine dependency crosses the service boundary: "
                f"{path.relative_to(repo_root).as_posix()}"
            )
    return errors


def _check_pinned_dependency(repo_root: Path) -> list[str]:
    errors: list[str] = []
    expected = f"{GPL_DEPENDENCY}=={GPL_DEPENDENCY_VERSION}"
    for name in ("requirements.txt", "requirements.lock"):
        path = repo_root / TEXT_ENGINE_RELATIVE / name
        text = _read(path)
        if text is None or expected not in text:
            errors.append(f"Text engine {name} must pin {expected}")
    test_lock = _read(repo_root / "tests/requirements-text-engine.lock")
    if test_lock is None or expected not in test_lock:
        errors.append("Text engine test dependency lock must pin the GPL dependency")
    return errors


def check_license_scope(repo_root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(_check_license_documents(repo_root))
    errors.extend(_check_text_engine_spdx(repo_root))
    errors.extend(_check_pinned_dependency(repo_root))
    errors.extend(_check_service_boundary(repo_root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    args = parser.parse_args()
    errors = check_license_scope(args.repo_root.resolve())
    if errors:
        for error in errors:
            print(f"LICENSE SCOPE: {error}", file=sys.stderr)
        return 1
    print("License scope check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
