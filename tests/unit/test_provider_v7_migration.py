from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.providers.db import MIGRATIONS, init_db


def _create_v6_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for version in range(1, 7):
            conn.executescript(MIGRATIONS[version])
        conn.execute("PRAGMA user_version = 6")
        for provider_id, provider_type in (
            ("openai", "openai_compatible"),
            ("engine", "engine_service"),
        ):
            conn.execute(
                """INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type,
                    is_enabled, is_default, response_format, created_at, updated_at,
                    scope, workspace_id, api_style
                ) VALUES (?, ?, ?, 'test', 'https://example.test/v1', 'none', 1, 0,
                    'node_output', '2026-01-01', '2026-01-01', 'workspace', 'ws-1', ?)""",
                (
                    provider_id,
                    provider_id,
                    provider_type,
                    "openai" if provider_type == "openai_compatible" else None,
                ),
            )


def test_empty_database_reaches_v7_without_auth_check(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    init_db(path)

    with sqlite3.connect(path) as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'model_providers'"
        ).fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_providers)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 7
    assert "CHECK (auth_type" not in sql
    assert {"api_protocol", "model_id", "model_display_name", "is_chatbot_default"} <= columns


def test_v6_to_v7_preserves_data_and_defaults(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    _create_v6_database(path)
    init_db(path)

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT id, api_protocol, is_chatbot_default FROM model_providers ORDER BY id"
        ).fetchall()
    assert rows == [("engine", None, 0), ("openai", None, 0)]


def test_v7_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "providers.db"
    init_db(path)
    init_db(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 7


def test_v8_duplicate_column_advances_schema_version(tmp_path: Path) -> None:
    path = init_db(tmp_path / "providers.db")
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_providers)")}
        assert "chatbot_ready" in columns
        conn.execute("PRAGMA user_version = 7")

    init_db(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 9


def test_v9_backfills_only_llm_model_capabilities(tmp_path: Path) -> None:
    path = init_db(tmp_path / "providers.db")
    with sqlite3.connect(path) as conn:
        common = (
            "test",
            "https://example.test/v1",
            "none",
            "node_output",
            "2026-01-01",
            "2026-01-01",
            "workspace",
            "ws-1",
        )
        conn.execute(
            """INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                response_format, created_at, updated_at, scope, workspace_id,
                api_protocol, model_id
            ) VALUES ('llm', 'LLM', 'llm_api', ?, ?, ?, ?, ?, ?, ?, ?,
                'openai_responses', 'gpt-test')""",
            common,
        )
        conn.execute(
            """INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                response_format, created_at, updated_at, scope, workspace_id
            ) VALUES ('engine', 'Engine', 'engine_service', ?, ?, ?, ?, ?, ?, ?, ?)""",
            common,
        )
        conn.execute(
            """UPDATE model_providers
                  SET model_context_window = NULL,
                      model_max_tokens = NULL,
                      model_reasoning = NULL"""
        )
        conn.execute("PRAGMA user_version = 8")

    init_db(path)

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """SELECT id, model_context_window, model_max_tokens, model_reasoning
                 FROM model_providers ORDER BY id"""
        ).fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 9
    assert rows == [("engine", None, None, None), ("llm", 128_000, 4_096, 0)]


def test_v9_requires_context_window_and_max_tokens_as_a_pair(tmp_path: Path) -> None:
    path = init_db(tmp_path / "providers.db")

    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                response_format, created_at, updated_at, scope, workspace_id
            ) VALUES (
                'engine', 'Engine', 'engine_service', 'ocr', 'http://ocr:8080', 'none',
                'node_output', '2026-01-01', '2026-01-01', 'workspace', 'ws-1'
            )"""
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE model_providers SET model_max_tokens = 4096 WHERE id = 'engine'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE model_providers SET model_context_window = 128000 WHERE id = 'engine'"
            )


def test_v7_failure_rolls_back_schema_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "providers.db"
    _create_v6_database(path)
    from app.providers import db

    def reject_rebuild(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE rollback_probe (id TEXT)")
        raise sqlite3.IntegrityError("forced migration failure")

    monkeypatch.setattr(db, "_rebuild_v7_provider_table", reject_rebuild)

    with pytest.raises(sqlite3.IntegrityError, match="forced migration failure"):
        init_db(path)

    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_providers)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "api_protocol" not in columns
    assert version == 6


def test_v7_enforces_llm_api_protocol_constraint(tmp_path: Path) -> None:
    path = init_db(tmp_path / "providers.db")
    values = (
        "id",
        "Chat",
        "llm_api",
        "llm",
        "https://api.example/v1",
        "none",
        "node_output",
        "2026-01-01",
        "2026-01-01",
        "workspace",
        "ws-1",
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type, response_format,
                created_at, updated_at, scope, workspace_id, api_protocol
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'openai_responses')""",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type, response_format,
                    created_at, updated_at, scope, workspace_id
                ) VALUES (
                    'missing', 'Missing', 'llm_api', 'llm', 'https://api.example/v1', 'none',
                    'node_output', '2026-01-01', '2026-01-01', 'workspace', 'ws-1'
                )"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type, response_format,
                    created_at, updated_at, scope, workspace_id, is_chatbot_default
                ) VALUES (
                    'engine-default', 'Engine', 'engine_service', 'ocr',
                    'http://ocr:8080', 'none', 'node_output', '2026-01-01', '2026-01-01',
                    'workspace', 'ws-1', 1
                )"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type, response_format,
                    created_at, updated_at, scope, workspace_id, api_protocol,
                    is_chatbot_default
                ) VALUES (
                    'system-default', 'System', 'llm_api', 'llm',
                    'https://api.example/v1', 'none', 'node_output', '2026-01-01',
                    '2026-01-01', 'system', NULL, 'openai_responses', 1
                )"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type, response_format,
                    created_at, updated_at, scope, workspace_id, api_protocol
                ) VALUES (
                    'wrong', 'Wrong', 'engine_service', 'llm', 'https://api.example/v1', 'none',
                    'node_output', '2026-01-01', '2026-01-01', 'workspace', 'ws-1',
                    'openai_responses'
                )"""
            )
