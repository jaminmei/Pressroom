import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.providers.db import MIGRATIONS, init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.seed import seed_default_providers
from app.providers.store import ProviderStore


def _create_v4_database(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        for version in (1, 2, 3):
            conn.executescript(MIGRATIONS[version])
        conn.executescript(MIGRATIONS[4])
        conn.execute("PRAGMA user_version = 4")
        conn.execute(
            """
            INSERT INTO model_providers (
                id, name, provider_type, engine_category, base_url, auth_type,
                is_enabled, is_default, response_format, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-rapidocr",
                "RapidOCR",
                "engine_service",
                "ocr",
                "http://ocr-engine:8080",
                "none",
                1,
                1,
                "node_output",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )


def test_old_row_remains_legacy_when_v5_migrates(tmp_path: Path) -> None:
    db_path = tmp_path / "providers.db"
    _create_v4_database(db_path)

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT scope, workspace_id FROM model_providers WHERE id = ?",
            ("legacy-rapidocr",),
        ).fetchone()
        indexes = {
            item[0]
            for item in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert row == ("legacy_unassigned", None)
    assert {"idx_providers_scope", "idx_providers_workspace_id", "idx_providers_default"} <= indexes
    assert version == 6


def test_new_seed_is_system(tmp_path: Path) -> None:
    db_path = init_db(tmp_path / "providers.db")
    store = ProviderStore(
        db_path=db_path,
        fernet=get_fernet(Fernet.generate_key().decode()),
    )

    seed_default_providers(store)

    assert {row.scope for row in store.list_providers(enabled_only=False)} == {ProviderScope.system}
    assert all(row.workspace_id is None for row in store.list_providers(enabled_only=False))


def test_new_user_provider_is_workspace_scoped(tmp_path: Path) -> None:
    db_path = init_db(tmp_path / "providers.db")
    store = ProviderStore(
        db_path=db_path,
        fernet=get_fernet(Fernet.generate_key().decode()),
    )

    row = store.create_provider(
        ModelProviderCreate(
            name="Workspace OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8002",
            scope=ProviderScope.workspace,
            workspace_id="ws-1",
        )
    )

    assert row.scope is ProviderScope.workspace
    assert row.workspace_id == "ws-1"


def test_invalid_scope_fails() -> None:
    with pytest.raises(ValidationError):
        ModelProviderCreate.model_validate_json(
            """{
                "name": "Invalid",
                "provider_type": "engine_service",
                "engine_category": "ocr",
                "base_url": "http://ocr:8002",
                "scope": "guessed_system"
            }"""
        )


def test_workspace_provider_requires_workspace_id() -> None:
    with pytest.raises(ValidationError):
        ModelProviderCreate(
            name="Workspace OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8002",
            scope=ProviderScope.workspace,
        )


def test_duplicate_workspace_default_fails(tmp_path: Path) -> None:
    db_path = init_db(tmp_path / "providers.db")
    with sqlite3.connect(db_path) as conn:
        values = (
            "engine_service",
            "ocr",
            "http://ocr:8002",
            "none",
            1,
            1,
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
            ) VALUES ('one', 'One', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO model_providers (
                    id, name, provider_type, engine_category, base_url, auth_type,
                    is_enabled, is_default, response_format, created_at, updated_at,
                    scope, workspace_id
                ) VALUES ('two', 'Two', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
