from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.repositories.task_run_repository import TaskRunRepository

WORKSPACE_ID = "ws_task_run_repository"


async def _build_repository(tmp_path: Path) -> TaskRunRepository:
    db_path = tmp_path / "task_run_repository.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    repository = TaskRunRepository(session_factory=session_factory)
    repository._test_engine = engine  # type: ignore[attr-defined]
    return repository


def test_upsert_snapshot_is_safe_under_concurrent_writes(tmp_path: Path) -> None:
    async def _run() -> None:
        task_run_repo = await _build_repository(tmp_path)
        try:
            task_id = "task-concurrent-upsert"

            async def _write(index: int) -> None:
                await task_run_repo.upsert_snapshot(
                    task_id=task_id,
                    status="completed",
                    workflow_id="wf-concurrency",
                    workflow_name="Concurrency Workflow",
                    source="evaluation",
                    workspace_id=WORKSPACE_ID,
                    evaluation_run_id="eval_run_concurrency",
                    created_at=datetime(2026, 3, 4, 10, 0, 0),
                    completed_at=datetime(2026, 3, 4, 10, 0, 1),
                    duration_ms=1000 + index,
                    node_summary={"total": 1, "completed": 1, "failed": 0},
                    result_preview=f"preview-{index}",
                    results=[{"result_id": f"res_{index:03d}"}],
                    error=None,
                    updated_at=datetime(2026, 3, 4, 10, 0, 1),
                )

            await asyncio.gather(*[_write(index) for index in range(10)])

            snapshot = await task_run_repo.get_snapshot(
                task_id,
                workspace_id=WORKSPACE_ID,
            )
            assert snapshot is not None
            assert snapshot.task_id == task_id
            assert snapshot.status == "completed"
            assert snapshot.workflow_id == "wf-concurrency"
            assert snapshot.source == "evaluation"
            assert snapshot.evaluation_run_id == "eval_run_concurrency"
        finally:
            await task_run_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_snapshot_datetime_is_normalized_to_utc(tmp_path: Path) -> None:
    async def _run() -> None:
        task_run_repo = await _build_repository(tmp_path)
        try:
            task_id = "task-datetime-normalize"
            naive_created_at = datetime(2026, 3, 4, 11, 30, 0)

            await task_run_repo.upsert_snapshot(
                task_id=task_id,
                status="completed",
                workflow_id="wf-datetime",
                workflow_name="Datetime Workflow",
                source="manual",
                workspace_id=WORKSPACE_ID,
                evaluation_run_id=None,
                created_at=naive_created_at,
                completed_at=naive_created_at,
                duration_ms=500,
                node_summary={"total": 1, "completed": 1, "failed": 0},
                result_preview="ok",
                results=[{"result_id": "res_001"}],
                error=None,
                updated_at=naive_created_at,
            )

            snapshot = await task_run_repo.get_snapshot(
                task_id,
                workspace_id=WORKSPACE_ID,
            )
            assert snapshot is not None
            assert snapshot.created_at is not None
            assert snapshot.created_at.tzinfo is not None
            assert snapshot.created_at.utcoffset() is not None
        finally:
            await task_run_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_snapshot_preserves_manual_source_without_evaluation_run(tmp_path: Path) -> None:
    async def _run() -> None:
        task_run_repo = await _build_repository(tmp_path)
        try:
            task_id = "task-manual-source"

            await task_run_repo.upsert_snapshot(
                task_id=task_id,
                status="running",
                workflow_id="wf-manual",
                workflow_name="Manual Workflow",
                source="manual",
                workspace_id=WORKSPACE_ID,
                evaluation_run_id=None,
                created_at=datetime(2026, 3, 4, 12, 0, 0),
                completed_at=None,
                duration_ms=None,
                node_summary={"total": 1, "completed": 0, "failed": 0},
                result_preview=None,
                results=None,
                error=None,
                updated_at=datetime(2026, 3, 4, 12, 0, 0),
            )

            snapshot = await task_run_repo.get_snapshot(
                task_id,
                workspace_id=WORKSPACE_ID,
            )
            assert snapshot is not None
            assert snapshot.source == "manual"
            assert snapshot.evaluation_run_id is None
        finally:
            await task_run_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_snapshot_preserves_workflow_and_file_bindings(tmp_path: Path) -> None:
    async def _run() -> None:
        task_run_repo = await _build_repository(tmp_path)
        try:
            workflow = {
                "nodes": [{"id": "input", "type": "input/text", "config": {}}],
                "connections": [],
            }
            input_files = [
                {
                    "node_id": "input",
                    "file_id": "file_123",
                    "filename": "source.txt",
                }
            ]
            await task_run_repo.upsert_snapshot(
                task_id="task-retry-snapshot",
                status="failed",
                workflow_id="wf-retry",
                workflow_name="Retry Workflow",
                source="manual",
                workspace_id=WORKSPACE_ID,
                evaluation_run_id=None,
                created_at=datetime(2026, 3, 4, 12, 0, 0),
                completed_at=datetime(2026, 3, 4, 12, 0, 1),
                duration_ms=1000,
                node_summary={"total": 1, "completed": 0, "failed": 1},
                result_preview=None,
                results=None,
                error="failed",
                input_files=input_files,
                workflow=workflow,
                updated_at=datetime(2026, 3, 4, 12, 0, 1),
            )

            snapshot = await task_run_repo.get_snapshot(
                "task-retry-snapshot",
                workspace_id=WORKSPACE_ID,
            )
            assert snapshot is not None
            assert snapshot.workflow == workflow
            assert snapshot.input_files == input_files
            assert snapshot.input_files[0]["file_id"] == "file_123"
        finally:
            await task_run_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())
