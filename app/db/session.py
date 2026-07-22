"""SQLAlchemy engine/session factories."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.db  # noqa: F401
from app.db.url import get_async_database_url, get_database_url


@lru_cache
def _get_engine() -> Engine:
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
    )


@lru_cache
def _get_async_engine() -> AsyncEngine:
    return create_async_engine(
        get_async_database_url(),
        pool_pre_ping=True,
    )


@lru_cache
def _get_session_factory() -> sessionmaker:
    return sessionmaker(
        bind=_get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@lru_cache
def _get_async_session_factory() -> async_sessionmaker:
    return async_sessionmaker(
        bind=_get_async_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


class _LazyFactoryProxy:
    def __init__(self, getter: Callable[[], Any]) -> None:
        self._getter = getter

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._getter()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)


class _LazyResourceProxy:
    def __init__(self, getter: Callable[[], Any]) -> None:
        self._getter = getter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)


engine = _LazyResourceProxy(_get_engine)
SessionLocal = _LazyFactoryProxy(_get_session_factory)
async_engine = _LazyResourceProxy(_get_async_engine)
AsyncSessionLocal = _LazyFactoryProxy(_get_async_session_factory)


__all__ = ["engine", "SessionLocal", "async_engine", "AsyncSessionLocal"]
