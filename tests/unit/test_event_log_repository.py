from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.db.task_event_log import TaskEventLog
from app.repositories.event_log_repository import EventLogRepository

SessionFactory = Callable[[], AsyncSession]
WORKSPACE_ID = "ws_event_log_repository"


@pytest_asyncio.fixture()
async def event_log_repo(
    tmp_path: Path,
) -> AsyncIterator[tuple[EventLogRepository, SessionFactory, Table]]:
    db_path = tmp_path / "event_log_repository.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("source", String, nullable=True),
        Column("workspace_id", String, nullable=True),
        Column("created_at", DateTime, nullable=True),
    )
    TaskEventLog.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventLogRepository(session_factory=session_factory), session_factory, task_runs
    await engine.dispose()


async def _seed_task_runs(
    session_factory: SessionFactory,
    task_runs_table: Table,
    task_run_ids: list[str],
) -> None:
    async with session_factory() as session:
        await session.execute(
            insert(task_runs_table),
            [{"id": task_run_id, "workspace_id": WORKSPACE_ID} for task_run_id in task_run_ids],
        )
        await session.commit()


async def _assign_task_run_workspace(
    session_factory: SessionFactory,
    task_runs_table: Table,
    task_run_id: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(task_runs_table)
            .where(task_runs_table.c.id == task_run_id)
            .values(workspace_id=WORKSPACE_ID)
        )
        await session.commit()


async def _task_run_exists(
    session_factory: SessionFactory,
    task_runs_table: Table,
    task_run_id: str,
) -> bool:
    statement = select(task_runs_table.c.id).where(task_runs_table.c.id == task_run_id)
    async with session_factory() as session:
        return await session.scalar(statement) == task_run_id


@pytest.mark.asyncio
async def test_append_persists_events_and_count_is_task_scoped(
    event_log_repo: tuple[EventLogRepository, SessionFactory, Table],
) -> None:
    repository, session_factory, task_runs_table = event_log_repo
    await _seed_task_runs(session_factory, task_runs_table, ["task-run-a", "task-run-b"])

    original_payload = {"status": "running"}
    first_event = await repository.append("task-run-a", "task_started", original_payload)
    original_payload["status"] = "mutated-after-append"

    second_event = await repository.append(
        "task-run-a",
        "task_progress",
        {"completed_steps": 2},
    )
    third_event = await repository.append(
        "task-run-b",
        "task_started",
        {"status": "running"},
    )

    assert first_event.seq < second_event.seq < third_event.seq
    assert first_event.payload == {"status": "running"}
    assert await repository.count("task-run-a", workspace_id=WORKSPACE_ID) == 2
    assert await repository.count("task-run-b", workspace_id=WORKSPACE_ID) == 1
    assert await repository.count("task-run-missing", workspace_id=WORKSPACE_ID) == 0


@pytest.mark.asyncio
async def test_append_auto_creates_task_run_for_foreign_key(
    event_log_repo: tuple[EventLogRepository, SessionFactory, Table],
) -> None:
    repository, session_factory, task_runs_table = event_log_repo

    event = await repository.append(
        "task-run-autocreate",
        "task_started",
        {"status": "running"},
    )

    assert event.task_run_id == "task-run-autocreate"
    assert await _task_run_exists(session_factory, task_runs_table, "task-run-autocreate")


@pytest.mark.asyncio
async def test_list_after_filters_by_cursor_exclusively_and_returns_ascending_order(
    event_log_repo: tuple[EventLogRepository, SessionFactory, Table],
) -> None:
    repository, session_factory, task_runs_table = event_log_repo
    await _seed_task_runs(session_factory, task_runs_table, ["task-run-a", "task-run-b"])

    event_1 = await repository.append("task-run-a", "event", {"idx": 1})
    await repository.append("task-run-b", "event", {"idx": 2})
    event_3 = await repository.append("task-run-a", "event", {"idx": 3})
    await repository.append("task-run-b", "event", {"idx": 4})
    await repository.append("task-run-b", "event", {"idx": 5})
    event_6 = await repository.append("task-run-a", "event", {"idx": 6})
    event_7 = await repository.append("task-run-a", "event", {"idx": 7})

    all_task_a_events = await repository.list_after(
        "task-run-a",
        cursor_seq=0,
        workspace_id=WORKSPACE_ID,
    )
    assert [event.seq for event in all_task_a_events] == [
        event_1.seq,
        event_3.seq,
        event_6.seq,
        event_7.seq,
    ]

    events_after_five = await repository.list_after(
        "task-run-a",
        cursor_seq=5,
        workspace_id=WORKSPACE_ID,
    )
    assert [event.seq for event in events_after_five] == [event_6.seq, event_7.seq]
    assert all(event.seq > 5 for event in events_after_five)
    assert {event.task_run_id for event in events_after_five} == {"task-run-a"}

    events_after_event_6 = await repository.list_after(
        "task-run-a",
        cursor_seq=event_6.seq,
        workspace_id=WORKSPACE_ID,
    )
    assert [event.seq for event in events_after_event_6] == [event_7.seq]

    assert (
        await repository.list_after(
            "task-run-a",
            cursor_seq=event_7.seq,
            workspace_id=WORKSPACE_ID,
        )
        == []
    )


@pytest.mark.asyncio
async def test_append_is_safe_for_concurrent_first_write_same_task(
    event_log_repo: tuple[EventLogRepository, SessionFactory, Table],
) -> None:
    repository, session_factory, task_runs_table = event_log_repo
    task_id = "task-run-concurrent-autocreate"

    async def _append(idx: int) -> int:
        event = await repository.append(
            task_id,
            "node_progress",
            {"idx": idx},
        )
        return event.seq

    seq_values = await asyncio.gather(*[_append(idx) for idx in range(10)])
    await _assign_task_run_workspace(session_factory, task_runs_table, task_id)

    assert len(seq_values) == 10
    assert len(set(seq_values)) == 10
    assert await repository.count(task_id, workspace_id=WORKSPACE_ID) == 10


@pytest.mark.asyncio
async def test_append_ensures_task_run_source_and_created_at(
    event_log_repo: tuple[EventLogRepository, SessionFactory, Table],
) -> None:
    repository, session_factory, task_runs_table = event_log_repo

    await repository.append("task-run-ensure", "test_event", {})

    async with session_factory() as session:
        result = await session.execute(
            select(task_runs_table.c.source, task_runs_table.c.created_at).where(
                task_runs_table.c.id == "task-run-ensure"
            )
        )
        row = result.fetchone()

    assert row is not None
    assert row.source == "event_log"
    assert row.created_at is not None
