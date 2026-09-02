"""SQLite DB layer for the provider store.

Handles database initialisation, schema migrations, and connection management
for the ``model_providers`` and ``provider_models`` tables.
"""

import contextlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Generator

# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------


def get_db_path() -> Path:
    """Return the SQLite database file path.

    Reads the ``PROVIDER_DB_PATH`` environment variable.  Falls back to
    ``./storage/providers.db`` when the variable is not set.

    Returns:
        Path: Resolved path to the SQLite database file.
    """
    raw = os.environ.get("PROVIDER_DB_PATH", "./storage/providers.db")
    return Path(raw)


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

MIGRATIONS: dict[int, str] = {
    1: """
CREATE TABLE IF NOT EXISTS model_providers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    provider_type   TEXT NOT NULL
                    CHECK (provider_type IN ('openai_compatible', 'engine_service')),
    engine_category TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    api_key         TEXT,
    auth_type       TEXT NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'api_key')),
    auth_config     TEXT,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    is_default      INTEGER NOT NULL DEFAULT 0,
    response_format TEXT NOT NULL DEFAULT 'doctags'
                    CHECK (response_format IN (
                        'doctags', 'simple_blocks', 'hocr',
                        'openai_chat', 'raw_text'
                    )),
    config_schema   TEXT,
    extra_config    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_models (
    id              TEXT PRIMARY KEY,
    provider_id     TEXT NOT NULL
                    REFERENCES model_providers(id) ON DELETE CASCADE,
    model_id        TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    capabilities    TEXT,
    default_config  TEXT,
    model_group     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(provider_id, model_id)
);

CREATE INDEX IF NOT EXISTS idx_providers_category ON model_providers(engine_category);
CREATE INDEX IF NOT EXISTS idx_providers_enabled  ON model_providers(is_enabled);
CREATE INDEX IF NOT EXISTS idx_models_provider    ON provider_models(provider_id);
""",
    2: """
ALTER TABLE model_providers ADD COLUMN health_url TEXT;
""",
    3: """
-- Rename response_format value 'doctags' -> 'node_output' and update constraints.
-- SQLite doesn't support ALTER COLUMN, so we recreate the table.

CREATE TABLE model_providers_new (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    provider_type   TEXT NOT NULL
                    CHECK (provider_type IN ('openai_compatible', 'engine_service')),
    engine_category TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    api_key         TEXT,
    auth_type       TEXT NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'api_key')),
    auth_config     TEXT,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    is_default      INTEGER NOT NULL DEFAULT 0,
    response_format TEXT NOT NULL DEFAULT 'node_output'
                    CHECK (response_format IN (
                        'node_output', 'simple_blocks', 'hocr',
                        'openai_chat', 'raw_text'
                    )),
    config_schema   TEXT,
    extra_config    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    health_url      TEXT
);

INSERT INTO model_providers_new
    SELECT id, name, provider_type, engine_category, base_url, api_key,
           auth_type, auth_config, is_enabled, is_default,
           CASE WHEN response_format = 'doctags' THEN 'node_output' ELSE response_format END,
           config_schema, extra_config, created_at, updated_at, health_url
    FROM model_providers;

DROP TABLE model_providers;
ALTER TABLE model_providers_new RENAME TO model_providers;

CREATE INDEX IF NOT EXISTS idx_providers_category ON model_providers(engine_category);
CREATE INDEX IF NOT EXISTS idx_providers_enabled  ON model_providers(is_enabled);
""",
    4: """
CREATE TABLE model_providers_new (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    provider_type   TEXT NOT NULL
                    CHECK (provider_type IN ('openai_compatible', 'engine_service')),
    engine_category TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    api_key         TEXT,
    auth_type       TEXT NOT NULL DEFAULT 'none',
    auth_config     TEXT,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    is_default      INTEGER NOT NULL DEFAULT 0,
    response_format TEXT NOT NULL DEFAULT 'node_output'
                    CHECK (response_format IN (
                        'node_output', 'simple_blocks', 'hocr',
                        'openai_chat', 'raw_text'
                    )),
    config_schema   TEXT,
    extra_config    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    health_url      TEXT
);

INSERT INTO model_providers_new
    SELECT id, name, provider_type, engine_category, base_url, api_key,
           auth_type, auth_config, is_enabled, is_default,
           response_format, config_schema, extra_config, created_at, updated_at, health_url
    FROM model_providers;

DROP TABLE model_providers;
ALTER TABLE model_providers_new RENAME TO model_providers;

CREATE INDEX IF NOT EXISTS idx_providers_category ON model_providers(engine_category);
CREATE INDEX IF NOT EXISTS idx_providers_enabled  ON model_providers(is_enabled);
""",
    5: """
ALTER TABLE model_providers ADD COLUMN workspace_id TEXT;
ALTER TABLE model_providers ADD COLUMN scope TEXT NOT NULL DEFAULT 'legacy_unassigned'
                CHECK (
                    scope IN ('system', 'workspace', 'legacy_unassigned')
                    AND (scope = 'workspace') =
                        (workspace_id IS NOT NULL AND length(workspace_id) > 0)
                );

CREATE INDEX IF NOT EXISTS idx_providers_scope ON model_providers(scope);
CREATE INDEX IF NOT EXISTS idx_providers_workspace_id ON model_providers(workspace_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_providers_default
    ON model_providers(scope, COALESCE(workspace_id, ''), engine_category)
    WHERE is_default = 1;
""",
    6: """
ALTER TABLE model_providers ADD COLUMN api_style TEXT
                CHECK (api_style IN ('openai', 'azure_openai') OR api_style IS NULL);
ALTER TABLE model_providers ADD COLUMN api_version TEXT;

UPDATE model_providers
   SET api_style = 'azure_openai',
       api_version = '2025-04-01-preview'
 WHERE provider_type = 'openai_compatible';

UPDATE model_providers
   SET api_style = NULL,
       api_version = NULL
 WHERE provider_type = 'engine_service';
    """,
    7: """Applied by _apply_migration_v7 because SQLite CHECK constraints require a rebuild.""",
    8: """Applied by _apply_migration_v8 (additive ALTER for chatbot_ready).""",
}


_AUTH_TYPE_CHECK_PATTERN = re.compile(r"CHECK\s*\(\s*auth_type\s+IN\s*\(", re.IGNORECASE)


def _has_legacy_auth_type_check(conn: sqlite3.Connection) -> bool:
    """Return whether ``model_providers.auth_type`` still has an enum CHECK."""

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'model_providers'"
    ).fetchone()
    return bool(row and row[0] and _AUTH_TYPE_CHECK_PATTERN.search(str(row[0])))


def _rebuild_v6_provider_table_without_auth_check(conn: sqlite3.Connection) -> None:
    """Recreate the v6 Provider table without freezing runtime auth registrations."""

    conn.execute(
        """
        CREATE TABLE model_providers_v6_new (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            provider_type   TEXT NOT NULL
                            CHECK (provider_type IN ('openai_compatible', 'engine_service')),
            engine_category TEXT NOT NULL,
            base_url        TEXT NOT NULL,
            api_key         TEXT,
            auth_type       TEXT NOT NULL DEFAULT 'none',
            auth_config     TEXT,
            is_enabled      INTEGER NOT NULL DEFAULT 1,
            is_default      INTEGER NOT NULL DEFAULT 0,
            response_format TEXT NOT NULL DEFAULT 'node_output'
                            CHECK (response_format IN (
                                'node_output', 'simple_blocks', 'hocr',
                                'openai_chat', 'raw_text'
                            )),
            config_schema   TEXT,
            extra_config    TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            health_url      TEXT,
            workspace_id    TEXT,
            scope           TEXT NOT NULL DEFAULT 'legacy_unassigned'
                            CHECK (
                                scope IN ('system', 'workspace', 'legacy_unassigned')
                                AND (scope = 'workspace') =
                                    (workspace_id IS NOT NULL AND length(workspace_id) > 0)
                            ),
            api_style       TEXT
                            CHECK (
                                api_style IN ('openai', 'azure_openai') OR api_style IS NULL
                            ),
            api_version     TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers_v6_new (
            id, name, provider_type, engine_category, base_url, api_key,
            auth_type, auth_config, is_enabled, is_default, response_format,
            config_schema, extra_config, created_at, updated_at, health_url,
            workspace_id, scope, api_style, api_version
        )
        SELECT
            id, name, provider_type, engine_category, base_url, api_key,
            auth_type, auth_config, is_enabled, is_default, response_format,
            config_schema, extra_config, created_at, updated_at, health_url,
            workspace_id, scope, api_style, api_version
        FROM model_providers
        """
    )
    conn.execute("DROP TABLE model_providers")
    conn.execute("ALTER TABLE model_providers_v6_new RENAME TO model_providers")
    conn.execute("CREATE INDEX idx_providers_category ON model_providers(engine_category)")
    conn.execute("CREATE INDEX idx_providers_enabled ON model_providers(is_enabled)")
    conn.execute("CREATE INDEX idx_providers_scope ON model_providers(scope)")
    conn.execute("CREATE INDEX idx_providers_workspace_id ON model_providers(workspace_id)")
    conn.execute(
        """
        CREATE UNIQUE INDEX idx_providers_default
            ON model_providers(scope, COALESCE(workspace_id, ''), engine_category)
            WHERE is_default = 1
        """
    )


def _rebuild_v7_provider_table(conn: sqlite3.Connection) -> None:
    """Recreate the Provider table with llm_api fields and constraints."""

    conn.execute(
        """
        CREATE TABLE model_providers_v7_new (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            provider_type TEXT NOT NULL
                CHECK (provider_type IN ('openai_compatible', 'engine_service', 'llm_api')),
            engine_category TEXT NOT NULL, base_url TEXT NOT NULL, api_key TEXT,
            auth_type TEXT NOT NULL DEFAULT 'none', auth_config TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            response_format TEXT NOT NULL DEFAULT 'node_output'
                CHECK (response_format IN (
                    'node_output', 'simple_blocks', 'hocr', 'openai_chat', 'raw_text'
                )),
            config_schema TEXT, extra_config TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            health_url TEXT, workspace_id TEXT,
            scope TEXT NOT NULL DEFAULT 'legacy_unassigned'
                CHECK (scope IN ('system', 'workspace', 'legacy_unassigned')
                    AND (scope = 'workspace') = (
                        workspace_id IS NOT NULL AND length(workspace_id) > 0
                    )),
            api_style TEXT CHECK (api_style IN ('openai', 'azure_openai') OR api_style IS NULL),
            api_version TEXT,
            api_protocol TEXT
                CHECK (
                    api_protocol IN (
                        'openai_chat_completions', 'openai_responses', 'anthropic_messages'
                    ) OR api_protocol IS NULL
                ),
            model_id TEXT, model_display_name TEXT,
            is_chatbot_default INTEGER NOT NULL DEFAULT 0,
            CHECK ((provider_type = 'llm_api') = (api_protocol IS NOT NULL)),
            CHECK (
                is_chatbot_default = 0
                OR (provider_type = 'llm_api' AND scope = 'workspace')
            )
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers_v7_new (
            id, name, provider_type, engine_category, base_url, api_key, auth_type, auth_config,
            is_enabled, is_default, response_format, config_schema, extra_config, created_at,
            updated_at, health_url, workspace_id, scope, api_style, api_version
        )
        SELECT id, name, provider_type, engine_category, base_url, api_key, auth_type, auth_config,
            is_enabled, is_default, response_format, config_schema, extra_config, created_at,
            updated_at, health_url, workspace_id, scope, api_style, api_version
        FROM model_providers
        """
    )
    conn.execute("DROP TABLE model_providers")
    conn.execute("ALTER TABLE model_providers_v7_new RENAME TO model_providers")
    conn.execute("CREATE INDEX idx_providers_category ON model_providers(engine_category)")
    conn.execute("CREATE INDEX idx_providers_enabled ON model_providers(is_enabled)")
    conn.execute("CREATE INDEX idx_providers_scope ON model_providers(scope)")
    conn.execute("CREATE INDEX idx_providers_workspace_id ON model_providers(workspace_id)")
    conn.execute(
        "CREATE UNIQUE INDEX idx_providers_default ON model_providers("
        "scope, COALESCE(workspace_id, ''), engine_category) WHERE is_default = 1"
    )


def apply_migrations(conn: sqlite3.Connection, current_version: int = 0) -> None:
    """Apply pending schema migrations to *conn*.

    The actual current schema version is read from ``PRAGMA user_version``
    (the ``current_version`` parameter is kept for API symmetry but is
    **not** used — the authoritative value always comes from the database).

    Migrations in :data:`MIGRATIONS` whose version number is greater than
    the current DB version are applied in ascending order.  After each
    migration the ``PRAGMA user_version`` is updated so that the operation
    is idempotent (safe to call multiple times).

    Auth strategy names are intentionally not enumerated in SQLite. Runtime
    Provider input models validate them against the auth strategy registry.

    Args:
        conn: An open :class:`sqlite3.Connection`.
        current_version: Ignored; the real version is read from the DB.
    """
    db_version: int = conn.execute("PRAGMA user_version").fetchone()[0]

    pending = sorted(ver for ver in MIGRATIONS if db_version < ver < 6)

    for ver in pending:
        conn.executescript(MIGRATIONS[ver])
        conn.execute(f"PRAGMA user_version = {ver}")
        conn.commit()

    if db_version < 6:
        _apply_migration_v6(conn)
    elif db_version == 6 and _has_legacy_auth_type_check(conn):
        _repair_v6_auth_type_schema(conn)
    if db_version < 7:
        _apply_migration_v7(conn)
    if db_version < 8:
        _apply_migration_v8(conn)
    if db_version < 9:
        _apply_migration_v9(conn)


def _apply_migration_v6(conn: sqlite3.Connection) -> None:
    """Apply Provider Store v6 atomically.

    ``executescript`` commits implicitly, so v6 deliberately uses individual
    statements inside an explicit transaction. A failed data migration leaves
    both the v5 schema and ``user_version`` intact.
    """

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            ALTER TABLE model_providers ADD COLUMN api_style TEXT
                CHECK (api_style IN ('openai', 'azure_openai') OR api_style IS NULL)
            """
        )
        conn.execute("ALTER TABLE model_providers ADD COLUMN api_version TEXT")
        conn.execute(
            """
            UPDATE model_providers
               SET api_style = 'azure_openai',
                   api_version = '2025-04-01-preview'
             WHERE provider_type = 'openai_compatible'
            """
        )
        conn.execute(
            """
            UPDATE model_providers
               SET api_style = NULL,
                   api_version = NULL
             WHERE provider_type = 'engine_service'
            """
        )
        if _has_legacy_auth_type_check(conn):
            _rebuild_v6_provider_table_without_auth_check(conn)
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _repair_v6_auth_type_schema(conn: sqlite3.Connection) -> None:
    """Repair legacy v6 databases while retaining schema version 6."""

    try:
        conn.execute("BEGIN IMMEDIATE")
        _rebuild_v6_provider_table_without_auth_check(conn)
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _apply_migration_v7(conn: sqlite3.Connection) -> None:
    """Apply Provider Store v7 atomically using the SQLite rebuild pattern."""

    try:
        conn.execute("BEGIN IMMEDIATE")
        _rebuild_v7_provider_table(conn)
        conn.execute("PRAGMA user_version = 7")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _apply_migration_v8(conn: sqlite3.Connection) -> None:
    """Apply Provider Store v8 atomically (additive chatbot_ready column)."""

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "ALTER TABLE model_providers ADD COLUMN chatbot_ready INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "duplicate column name" in str(exc).lower():
            conn.execute("PRAGMA user_version = 8")
            conn.commit()
            return
        raise


def _apply_migration_v9(conn: sqlite3.Connection) -> None:
    """Add explicit Pi model capability metadata and backfill existing rows."""

    try:
        conn.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_providers)")}
        if "model_context_window" not in columns:
            conn.execute(
                """ALTER TABLE model_providers
                   ADD COLUMN model_context_window INTEGER
                   CHECK (model_context_window BETWEEN 1 AND 9007199254740991)"""
            )
        if "model_max_tokens" not in columns:
            conn.execute(
                """ALTER TABLE model_providers
                   ADD COLUMN model_max_tokens INTEGER
                   CHECK (
                       (model_max_tokens IS NULL AND model_context_window IS NULL)
                       OR (
                           model_max_tokens IS NOT NULL
                           AND model_context_window IS NOT NULL
                           AND model_max_tokens BETWEEN 1 AND model_context_window
                       )
                   )"""
            )
        if "model_reasoning" not in columns:
            conn.execute(
                """ALTER TABLE model_providers
                   ADD COLUMN model_reasoning INTEGER
                   CHECK (model_reasoning IN (0, 1) OR model_reasoning IS NULL)"""
            )
        conn.execute(
            """UPDATE model_providers
               SET model_context_window = COALESCE(model_context_window, 128000),
                   model_max_tokens = COALESCE(model_max_tokens, 4096),
                   model_reasoning = COALESCE(model_reasoning, 0)
             WHERE provider_type = 'llm_api'"""
        )
        conn.execute("PRAGMA user_version = 9")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db(db_path: Path | None = None) -> Path:
    """Initialise the SQLite database, creating it if necessary.

    Ensures the parent directory exists, opens a connection, and applies any
    pending migrations via :func:`apply_migrations`.

    Args:
        db_path: Path to the database file.  When *None*, :func:`get_db_path`
            is called to resolve the default path.

    Returns:
        Path: The path to the (now initialised) database file.
    """
    if db_path is None:
        db_path = get_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        apply_migrations(conn, current_version=0)
    finally:
        conn.close()

    return db_path


# ---------------------------------------------------------------------------
# Connection context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def get_connection(
    db_path: Path,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a :class:`sqlite3.Connection` with auto-commit / rollback.

    Each row is exposed as a :class:`sqlite3.Row` (accessible by column name).
    Foreign-key enforcement is enabled for the lifetime of the connection.

    The transaction is committed on clean exit and rolled back on any
    exception; the connection is always closed in the ``finally`` block.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        sqlite3.Connection: An open, configured database connection.

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Example::

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO model_providers ...")
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
