from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-workspace-runtime-env.py")
SECRET_DATABASE_URL = "postgresql://runtime-user:database-secret@db/runtime"
SECRET_PROVIDER_KEY = "provider-secret-key"


def run_checker(
    *,
    overrides: dict[str, str] | None = None,
    expect: str = "true",
    peer_role: str = "backend",
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "WORKSPACE_RBAC_ENFORCED": expect,
        "DATABASE_URL": SECRET_DATABASE_URL,
        "PROVIDER_DB_PATH": "/app/storage/providers.db",
        "PROVIDER_ENCRYPTION_KEY": SECRET_PROVIDER_KEY,
    }
    env.update(overrides or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--peer-role", peer_role, "--expect-enforced", expect],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_complete_local_runtime_passes() -> None:
    result = run_checker()

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["checks"]["database_url_present"] is True
    assert report["checks"]["provider_encryption_key_present"] is True


def test_expect_enforced_false_passes_when_effective_value_is_false() -> None:
    result = run_checker(expect="false")

    assert result.returncode == 0
    assert json.loads(result.stdout)["checks"]["workspace_rbac_enforced_matches"] is True


def test_deprecated_worker_role_option_remains_compatible() -> None:
    result = run_checker(peer_role="worker")

    assert result.returncode == 0


def test_missing_required_value_fails() -> None:
    result = run_checker(overrides={"PROVIDER_ENCRYPTION_KEY": ""})

    assert result.returncode != 0
    assert json.loads(result.stdout)["checks"]["provider_encryption_key_present"] is False


def test_output_never_prints_secrets() -> None:
    result = run_checker(overrides={"WORKSPACE_RBAC_ENFORCED": "invalid"})
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert SECRET_DATABASE_URL not in output
    assert SECRET_PROVIDER_KEY not in output
