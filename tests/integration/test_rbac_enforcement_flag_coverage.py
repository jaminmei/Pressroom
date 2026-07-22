from __future__ import annotations

import importlib
from pathlib import Path
from subprocess import CompletedProcess, run


def test_workspace_rbac_artifacts_are_present() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    support_module = importlib.import_module("tests.integration.workspace_api_support")

    assert hasattr(support_module, "workspace_api_harness")
    assert "WORKSPACE_RBAC_ENFORCED=true" in (root_dir / "SECURITY.md").read_text()
    assert "WORKSPACE_RBAC_ENFORCED=true" in (root_dir / ".env.example").read_text()


def test_rbac_enforcement_flag_coverage_script_passes() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    result: CompletedProcess[str] = run(
        ["bash", "scripts/check-rbac-test-coverage.sh"],
        cwd=root_dir,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
