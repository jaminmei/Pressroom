from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from app.providers.db import init_db

SCRIPT: Final = Path(__file__).with_name("assign-legacy-providers.py")


def _insert_provider(
    db_path: Path,
    provider_id: str,
    *,
    category: str = "ocr",
    api_key: str = "secret-api-key",
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, api_key,
                auth_type, auth_config, is_enabled, is_default, response_format,
                created_at, updated_at, scope, workspace_id
            ) VALUES (?, ?, 'engine_service', ?, ?, ?, 'api_key', ?, 1, 1,
                      'node_output', ?, ?, 'legacy_unassigned', NULL)
            """,
            (
                provider_id,
                f"Provider {provider_id}",
                category,
                "https://provider.invalid",
                api_key,
                '{"client_secret":"secret-client-value"}',
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )


@pytest.fixture
def provider_db(tmp_path: Path) -> Path:
    db_path = init_db(tmp_path / "providers.db")
    _insert_provider(db_path, "legacy-ocr")
    _insert_provider(db_path, "legacy-text", category="text")
    return db_path


def _run(db_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PROVIDER_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_approval_files(
    tmp_path: Path,
    report_path: Path,
    mappings: list[dict[str, str | bool]],
) -> tuple[Path, Path, str]:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mappings), encoding="utf-8")
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    mapping_sha = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "report_sha256": report_sha,
                "mapping_sha256": mapping_sha,
                "approver": "provider-owner",
                "approval_utc": "2026-07-15T00:00:00Z",
                "approved_ids": [item["provider_id"] for item in mappings],
            }
        ),
        encoding="utf-8",
    )
    return mapping_path, approval_path, report_sha


def _system_mappings() -> list[dict[str, str | bool]]:
    return [
        {
            "provider_id": "legacy-ocr",
            "scope": "system",
            "expected_category": "ocr",
            "expected_is_default": True,
        },
        {
            "provider_id": "legacy-text",
            "scope": "system",
            "expected_category": "text",
            "expected_is_default": True,
        },
    ]


def test_report_writes_auditable_non_secret_json(provider_db: Path, tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    result = _run(provider_db, "--report", "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["database"]["path"] == str(provider_db.resolve())
    assert len(report["database"]["sha256"]) == 64
    assert report["schema_version"] == 6
    assert {item["id"] for item in report["providers"]} == {
        "legacy-ocr",
        "legacy-text",
    }
    assert all(len(item["row_sha256"]) == 64 for item in report["providers"])
    serialized = output.read_text(encoding="utf-8")
    assert "secret-api-key" not in serialized
    assert "secret-client-value" not in serialized


def test_report_is_the_default_mode(provider_db: Path) -> None:
    result = _run(provider_db)

    assert result.returncode == 0
    assert json.loads(result.stdout)["count"] == 2


def test_dry_run_validates_without_changing_database(provider_db: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    assert _run(provider_db, "--report", "--output", str(report_path)).returncode == 0
    mapping, approval, report_sha = _write_approval_files(tmp_path, report_path, _system_mappings())
    before = provider_db.read_bytes()

    result = _run(
        provider_db,
        "--mapping",
        str(mapping),
        "--approval",
        str(approval),
        "--expected-report-sha256",
        report_sha,
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "validated"
    assert provider_db.read_bytes() == before


def test_apply_changes_only_mapped_rows_and_rerun_is_idempotent(
    provider_db: Path, tmp_path: Path
) -> None:
    with sqlite3.connect(provider_db) as connection:
        connection.execute(
            """
            INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                is_enabled, is_default, response_format, created_at, updated_at,
                scope, workspace_id
            ) VALUES ('unrelated', 'Unrelated', 'engine_service', 'vlm',
                      'https://unrelated.invalid', 'none', 1, 0, 'node_output',
                      '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                      'system', NULL)
            """
        )
    report_path = tmp_path / "report.json"
    assert _run(provider_db, "--report", "--output", str(report_path)).returncode == 0
    mapping, approval, report_sha = _write_approval_files(tmp_path, report_path, _system_mappings())
    arguments = (
        "--mapping",
        str(mapping),
        "--approval",
        str(approval),
        "--expected-report-sha256",
        report_sha,
        "--apply",
    )

    first = _run(provider_db, *arguments)
    second = _run(provider_db, *arguments)

    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout)["status"] == "applied"
    assert json.loads(second.stdout)["status"] == "already_applied"
    with sqlite3.connect(provider_db) as connection:
        rows = connection.execute(
            "SELECT id, scope, workspace_id FROM model_providers ORDER BY id"
        ).fetchall()
    assert rows == [
        ("legacy-ocr", "system", None),
        ("legacy-text", "system", None),
        ("unrelated", "system", None),
    ]


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (_system_mappings()[:1], "legacy ID set differs"),
        (
            _system_mappings()
            + [
                {
                    "provider_id": "unknown",
                    "scope": "system",
                    "expected_category": "ocr",
                    "expected_is_default": True,
                }
            ],
            "unknown provider IDs",
        ),
        (
            [{**_system_mappings()[0], "scope": "workspace"}, _system_mappings()[1]],
            "workspace scope requires workspace_id",
        ),
        (
            [{**_system_mappings()[0], "workspace_id": "ws-1"}, _system_mappings()[1]],
            "system scope cannot have workspace_id",
        ),
        (
            [{**_system_mappings()[0], "scope": "guessed_system"}, _system_mappings()[1]],
            "invalid scope",
        ),
        (
            [{**_system_mappings()[0], "expected_category": "vlm"}, _system_mappings()[1]],
            "category changed",
        ),
    ],
)
def test_mapping_validation_rejects_drift_and_invalid_scope(
    provider_db: Path,
    tmp_path: Path,
    mapping: list[dict[str, str | bool]],
    message: str,
) -> None:
    report_path = tmp_path / "report.json"
    assert _run(provider_db, "--report", "--output", str(report_path)).returncode == 0
    mapping_path, approval, report_sha = _write_approval_files(tmp_path, report_path, mapping)

    result = _run(
        provider_db,
        "--mapping",
        str(mapping_path),
        "--approval",
        str(approval),
        "--expected-report-sha256",
        report_sha,
        "--dry-run",
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_rejects_invalid_mode_combinations(provider_db: Path) -> None:
    result = _run(provider_db, "--apply")

    assert result.returncode != 0


def test_rejects_approval_or_report_hash_mismatch(provider_db: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    assert _run(provider_db, "--report", "--output", str(report_path)).returncode == 0
    mapping, approval, _ = _write_approval_files(tmp_path, report_path, _system_mappings())

    result = _run(
        provider_db,
        "--mapping",
        str(mapping),
        "--approval",
        str(approval),
        "--expected-report-sha256",
        "0" * 64,
        "--dry-run",
    )

    assert result.returncode != 0
    assert "report SHA-256" in result.stderr
