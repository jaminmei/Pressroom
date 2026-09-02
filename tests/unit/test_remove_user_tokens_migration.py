from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260828_0026_remove_user_tokens.py"
)


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("remove_user_tokens_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remove_user_tokens_migration_round_trip(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'user-token-removal.sqlite3'}")
    migration = _migration_module()
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL)")
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        migration.op = operations

        migration.downgrade()
        assert "user_tokens" in inspect(connection).get_table_names()

        migration.upgrade()
        assert "user_tokens" not in inspect(connection).get_table_names()

        migration.upgrade()
        assert "user_tokens" not in inspect(connection).get_table_names()
    engine.dispose()
