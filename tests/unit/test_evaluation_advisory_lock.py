"""Focused tests for evaluation cancellation/publishing advisory-lock discipline.

PostgreSQL-specific concurrency behavior is covered by integration tests.
These unit tests use monkeypatched dialect detection + a stub session factory
to verify the lock/unlock calls happen in the right order without requiring
a real Postgres connection.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.repositories.evaluation_repository import EvaluationRepository


class _StubResult:
    def scalars(self) -> "_StubScalars":
        return _StubScalars()

    def scalar(self) -> Any:
        return None


class _StubScalars:
    def all(self) -> list[Any]:
        return []


class _LockSession:
    def __init__(self, captured: list[tuple[str, dict[str, Any]]]) -> None:
        self._captured = captured
        self.closed = False

    async def __aenter__(self) -> "_LockSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _StubResult:
        self._captured.append((str(statement), params or {}))
        return _StubResult()

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class _MainSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def __aenter__(self) -> "_MainSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None

    async def scalars(self, *_a: object, **_k: object) -> _StubScalars:
        return _StubScalars()

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _StubResult:
        return _StubResult()

    async def commit(self) -> None:
        return None

    async def refresh(self, *_a: object, **_k: object) -> None:
        return None

    def add(self, *_a: object, **_k: object) -> None:
        return None


class _PublisherLockSession(_LockSession):
    def __init__(self, captured: list[tuple[str, dict[str, Any]]]) -> None:
        super().__init__(captured)
        self._scalar_calls = 0

    async def scalar(self, *_a: object, **_k: object) -> str | int:
        self._scalar_calls += 1
        return "eval_run_lock" if self._scalar_calls == 1 else 1

    def get_bind(self) -> object:
        return type(
            "FakeBind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()


def _patch_dialect(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    fake_sync_engine = type(
        "FakeSyncEngine",
        (),
        {"dialect": type("Dialect", (), {"name": name})()},
    )()
    monkeypatch.setattr(
        "app.db.session.engine",
        type("FakeAsyncEngine", (), {"sync_engine": fake_sync_engine})(),
    )


async def _async_empty() -> list[str]:
    return []


@pytest.mark.asyncio
async def test_cancel_run_takes_and_releases_session_advisory_lock_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_calls: list[tuple[str, dict[str, Any]]] = []
    lock_session = _LockSession(lock_calls)
    main_session = _MainSession()

    repo = EvaluationRepository(session_factory=lambda: main_session)  # type: ignore[arg-type]
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: lock_session)
    _patch_dialect(monkeypatch, "postgresql")
    monkeypatch.setattr(
        EvaluationRepository,
        "_collect_published_task_ids",
        lambda self, run_id: _async_empty(),
    )

    result = await repo.cancel_run("eval_run_lock", workspace_id="ws_lock")

    assert result is None
    assert any("pg_advisory_lock" in stmt and "hashtext" in stmt for stmt, _ in lock_calls), (
        f"expected pg_advisory_lock in lock session calls: {lock_calls}"
    )
    assert any("pg_advisory_unlock" in stmt and "hashtext" in stmt for stmt, _ in lock_calls), (
        f"expected pg_advisory_unlock in lock session calls: {lock_calls}"
    )
    lock_index = next(i for i, (stmt, _) in enumerate(lock_calls) if "pg_advisory_lock" in stmt)
    unlock_index = next(i for i, (stmt, _) in enumerate(lock_calls) if "pg_advisory_unlock" in stmt)
    assert lock_index < unlock_index, "lock must be acquired before unlock"


@pytest.mark.asyncio
async def test_cancel_run_skips_advisory_lock_on_non_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_calls: list[tuple[str, dict[str, Any]]] = []
    main_session = _MainSession()

    repo = EvaluationRepository(session_factory=lambda: main_session)  # type: ignore[arg-type]
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: _LockSession(lock_calls))
    _patch_dialect(monkeypatch, "sqlite")
    monkeypatch.setattr(
        EvaluationRepository,
        "_collect_published_task_ids",
        lambda self, run_id: _async_empty(),
    )

    result = await repo.cancel_run("eval_run_nolock", workspace_id="ws_nolock")

    assert result is None
    assert lock_calls == [], f"expected no advisory lock calls on sqlite: {lock_calls}"


@pytest.mark.asyncio
async def test_publish_guard_uses_the_cancellation_advisory_lock() -> None:
    lock_calls: list[tuple[str, dict[str, Any]]] = []
    lock_session = _PublisherLockSession(lock_calls)
    repository = EvaluationDispatchRepository(  # type: ignore[arg-type]
        session_factory=lambda: lock_session
    )

    async with repository.publish_guard("outbox_1") as can_publish:
        assert can_publish is True
        assert any("pg_advisory_lock" in statement for statement, _ in lock_calls)
        assert not any("pg_advisory_unlock" in statement for statement, _ in lock_calls)

    assert any("pg_advisory_unlock" in statement for statement, _ in lock_calls)
    assert all(params == {"rid": "eval_run_lock"} for _, params in lock_calls)
    assert lock_session.closed is True
