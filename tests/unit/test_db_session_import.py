from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_app_main_import_does_not_require_database_env() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("POSTGRES_PASSWORD", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
