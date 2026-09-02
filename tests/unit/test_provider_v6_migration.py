from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.providers.db import MIGRATIONS, init_db


def _legacy_v4_migration() -> str:
    current_column = "auth_type       TEXT NOT NULL DEFAULT 'none',"
    legacy_column = """auth_type       TEXT NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'api_key')),"""
    assert current_column in MIGRATIONS[4]
    return MIGRATIONS[4].replace(current_column, legacy_column, 1)


def _provider_table_sql(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'model_providers'"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _create_v5_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for version in (1, 2, 3):
            conn.executescript(MIGRATIONS[version])
        conn.executescript(_legacy_v4_migration())
        conn.executescript(MIGRATIONS[5])
        conn.execute("PRAGMA user_version = 5")
        common = (
            "vlm",
            "https://provider.example/v1",
            "none",
            1,
            0,
            "node_output",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "workspace",
            "ws-1",
        )
        conn.execute(
            """
            INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                is_enabled, is_default, response_format, created_at, updated_at,
                scope, workspace_id
            ) VALUES ('legacy-vlm', 'Legacy VLM', 'openai_compatible', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            common,
        )
        conn.execute(
            """
            INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                is_enabled, is_default, response_format, created_at, updated_at,
                scope, workspace_id
            ) VALUES (
                'legacy-ocr', 'Legacy OCR', 'engine_service', 'ocr',
                'http://ocr:8080', 'none', 1, 0, 'node_output',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                'workspace', 'ws-1'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO provider_models (
                id, provider_id, model_id, display_name, is_enabled, sort_order
            ) VALUES ('model-row', 'legacy-vlm', 'deployment-a', 'Deployment A', 1, 0)
            """
        )


def _create_legacy_v6_database(path: Path) -> None:
    _create_v5_database(path)
    with sqlite3.connect(path) as conn:
        conn.executescript(MIGRATIONS[6])
        conn.execute("PRAGMA user_version = 6")


def test_empty_database_reaches_v6_without_auth_type_check(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"

    init_db(path)

    assert "CHECK (auth_type" not in _provider_table_sql(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 6


def test_v5_to_v6_preserves_legacy_azure_semantics_and_models(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    _create_v5_database(path)

    init_db(path)

    with sqlite3.connect(path) as conn:
        vlm = conn.execute(
            "SELECT api_style, api_version FROM model_providers WHERE id = 'legacy-vlm'"
        ).fetchone()
        ocr = conn.execute(
            "SELECT api_style, api_version FROM model_providers WHERE id = 'legacy-ocr'"
        ).fetchone()
        model_count = conn.execute("SELECT COUNT(*) FROM provider_models").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert vlm == ("azure_openai", "2025-04-01-preview")
    assert ocr == (None, None)
    assert model_count == 1
    assert version >= 6
    assert "CHECK (auth_type" not in _provider_table_sql(path)


def test_existing_v6_auth_type_check_is_repaired_without_version_bump(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    _create_legacy_v6_database(path)
    assert "CHECK (auth_type" in _provider_table_sql(path)

    init_db(path)

    assert "CHECK (auth_type" not in _provider_table_sql(path)
    with sqlite3.connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        providers = conn.execute("SELECT COUNT(*) FROM model_providers").fetchone()[0]
        models = conn.execute("SELECT COUNT(*) FROM provider_models").fetchone()[0]
    assert version >= 6
    assert providers == 2
    assert models == 1


def test_v6_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    _create_v5_database(path)
    init_db(path)
    init_db(path)

    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(model_providers)")]
        assert columns.count("api_style") == 1
        assert columns.count("api_version") == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 6


def test_v6_failure_rolls_back_schema_and_version(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    _create_v5_database(path)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TRIGGER reject_provider_update
            BEFORE UPDATE ON model_providers
            BEGIN
                SELECT RAISE(ABORT, 'forced migration failure');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced migration failure"):
        init_db(path)

    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(model_providers)")]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "api_style" not in columns
    assert "api_version" not in columns
    assert version == 5
