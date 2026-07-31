from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-license-scope.py")
SPDX = "SPDX-License-Identifier: GPL-3.0-only"


def _prepare_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    text_engine = repo / "engines/text"
    text_engine.mkdir(parents=True)
    canonical_gpl = Path(__file__).resolve().parents[1] / "LICENSES/GPL-3.0-only.txt"
    gpl_text = canonical_gpl.read_text(encoding="utf-8")
    (repo / "LICENSES").mkdir()
    (repo / "LICENSES/GPL-3.0-only.txt").write_text(gpl_text, encoding="utf-8")
    (text_engine / "COPYING").write_text(gpl_text, encoding="utf-8")
    (repo / "LICENSE").write_text(
        "MIT License\nCopyright (c) Jamin Mei\nCopyright (c) ricoyudog\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("engines/text/** uses GPL-3.0-only\n", encoding="utf-8")
    (repo / "THIRD_PARTY_NOTICES.md").write_text(
        "html2text==2020.1.16 is GPL-3.0-only; dependency locks are "
        "`frontend/package-lock.json` and `website/package-lock.json`.\n",
        encoding="utf-8",
    )
    (text_engine / "README.md").write_text(
        f"<!-- {SPDX} -->\nengines/text/** uses GPL-3.0-only\n",
        encoding="utf-8",
    )
    (text_engine / "requirements.txt").write_text(
        f"# {SPDX}\nhtml2text==2020.1.16\n",
        encoding="utf-8",
    )
    (text_engine / "requirements.lock").write_text(
        f"# {SPDX}\nhtml2text==2020.1.16 \\\n    --hash=sha256:{'0' * 64}\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "requirements-text-engine.lock").write_text(
        f"html2text==2020.1.16 \\\n    --hash=sha256:{'0' * 64}\n",
        encoding="utf-8",
    )
    source = text_engine / "src/text_engine.py"
    source.parent.mkdir()
    source.write_text(f"# {SPDX}\nVALUE = 1\n", encoding="utf-8")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_accepts_declared_text_engine_license_scope(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)

    result = _run(repo)

    assert result.returncode == 0, result.stderr


def test_rejects_missing_text_engine_spdx_header(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    (repo / "engines/text/src/text_engine.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(repo)

    assert result.returncode == 1
    assert "Text engine file lacks the GPL SPDX header" in result.stderr


def test_rejects_missing_website_lock_notice(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    notices = repo / "THIRD_PARTY_NOTICES.md"
    notices.write_text(
        "html2text==2020.1.16 is GPL-3.0-only; dependency lock is `frontend/package-lock.json`.\n",
        encoding="utf-8",
    )

    result = _run(repo)

    assert result.returncode == 1
    assert "third-party notices must identify website/package-lock.json" in result.stderr


def test_ignores_generated_python_bytecode(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    bytecode = repo / "engines/text/src/__pycache__/text_engine.cpython-312.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"\x00\x01generated")

    result = _run(repo)

    assert result.returncode == 0, result.stderr


def test_rejects_gpl_import_across_service_boundary(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    application = repo / "app/main.py"
    application.parent.mkdir()
    application.write_text("import html2text\n", encoding="utf-8")

    result = _run(repo)

    assert result.returncode == 1
    assert "GPL Text engine import crosses the service boundary: app/main.py" in result.stderr


def test_rejects_gpl_dependency_outside_text_engine(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    (repo / "requirements.txt").write_text("html2text==2020.1.16\n", encoding="utf-8")

    result = _run(repo)

    assert result.returncode == 1
    assert (
        "GPL Text engine dependency crosses the service boundary: requirements.txt" in result.stderr
    )


def test_rejects_missing_text_engine_test_lock(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    (repo / "tests/requirements-text-engine.lock").unlink()

    result = _run(repo)

    assert result.returncode == 1
    assert "Text engine test dependency lock must pin the GPL dependency" in result.stderr
