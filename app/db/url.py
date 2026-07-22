"""Database URL helpers shared by runtime and Alembic."""

from __future__ import annotations

import os
from urllib.parse import quote_plus


def get_database_url() -> str:
    """Resolve the SQLAlchemy URL from env, with PostgreSQL defaults."""
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = os.getenv("POSTGRES_USER", "docconv")
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD environment variable is required")
    password = quote_plus(password)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "docconv")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def get_async_database_url() -> str:
    """Resolve an async SQLAlchemy URL from current configuration."""
    url = get_database_url()

    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    return url
