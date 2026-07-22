from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.db.evaluation_dispatch_outbox import (
    DISPATCH_CANCELLED,
    DISPATCH_PENDING,
    DISPATCH_PUBLISHED,
    DISPATCH_PUBLISHING,
    EvaluationDispatchOutbox,
)
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.task_run import TaskRun
from app.models.db.workspace import Workspace
from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.test_set_repository import TestSetRepository


async def _build_repositories(
    tmp_path: Path,
) -> tuple[TestSetRepository, EvaluationRepository, EvaluationDispatchRepository, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dispatch.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return (
        TestSetRepository(session_factory=session_factory),
        EvaluationRepository(session_factory=session_factory),
        EvaluationDispatchRepository(session_factory=session_factory),
        engine,
    )


async def _create_queue_run(
    tmp_path: Path,
) -> tuple[TestSetRepository, EvaluationRepository, EvaluationDispatchRepository, object, object]:
    test_sets, evaluations, dispatch, engine = await _build_repositories(tmp_path)
    test_set = await test_sets.create_test_set(
        name="Queue set",
        description=None,
        workspace_id="ws_queue",
    )
    document = await test_sets.create_test_document(
        test_set_id=test_set.id,
        filename="one.pdf",
        mime_type="application/pdf",
        storage_path=f"test_sets/{test_set.id}/one.pdf",
        size_bytes=10,
        page_count=1,
    )
    run, results = await evaluations.create_run_with_results(
        test_set_id=test_set.id,
        workflow_id="wf_queue",
        workflow_version=1,
        workflow_snapshot_json={"nodes": []},
        name="Queue run",
        total_documents=1,
        document_ids=[document.id],
        workspace_id="ws_queue",
        queue_mode=True,
    )
    return test_sets, evaluations, dispatch, engine, (run, results[0])


def test_queue_creation_is_atomic_and_creates_deterministic_placeholders(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine, payload = await _create_queue_run(tmp_path)
        run, result = payload
        try:
            assert result.status == "queued"
            assert result.task_run_id == f"eval_task_{run.id}_{result.document_id}"
            task = await _load_task(engine, result.task_run_id)
            assert task is not None
            assert task.status == "queued"
            assert task.workspace_id == "ws_queue"
            rows = await dispatch.list_for_run(run.id)
            assert len(rows) == 1
            assert rows[0].evaluation_result_id == result.id
            assert rows[0].task_run_id == result.task_run_id
            assert rows[0].status == DISPATCH_PENDING
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_queue_creation_respects_foreign_key_insert_order(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dispatch-fk.sqlite3'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def _run() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        test_sets = TestSetRepository(session_factory=session_factory)
        evaluations = EvaluationRepository(session_factory=session_factory)
        workspace_id = "ws_fk_order"

        try:
            async with session_factory() as session:
                session.add(Workspace(id=workspace_id, name="FK order workspace"))
                await session.commit()

            test_set = await test_sets.create_test_set(
                name="FK order set",
                description=None,
                workspace_id=workspace_id,
            )
            document_ids: list[str] = []
            for index in range(2):
                document = await test_sets.create_test_document(
                    test_set_id=test_set.id,
                    filename=f"document-{index}.pdf",
                    mime_type="application/pdf",
                    storage_path=f"test_sets/{test_set.id}/document-{index}.pdf",
                    size_bytes=10,
                    page_count=1,
                )
                document_ids.append(document.id)

            run, results = await evaluations.create_run_with_results(
                test_set_id=test_set.id,
                workflow_id="wf_fk_order",
                workflow_version=1,
                workflow_snapshot_json={"nodes": []},
                name="FK order run",
                total_documents=len(document_ids),
                document_ids=document_ids,
                workspace_id=workspace_id,
                queue_mode=True,
            )

            async with session_factory() as session:
                assert len(results) == 2
                assert (
                    await session.scalar(
                        select(func.count(EvaluationRun.id)).where(EvaluationRun.id == run.id)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(TaskRun.id)).where(TaskRun.evaluation_run_id == run.id)
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count(EvaluationResult.id)).where(
                            EvaluationResult.evaluation_run_id == run.id
                        )
                    )
                    == 2
                )
                assert await session.scalar(select(func.count(EvaluationDispatchOutbox.id))) == 2
                assert (await session.execute(text("PRAGMA foreign_key_check"))).all() == []
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_serial_creation_does_not_create_dispatch_work(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine = await _build_repositories(tmp_path)
        try:
            test_set = await test_sets.create_test_set(
                name="Serial set", description=None, workspace_id="ws_serial"
            )
            document = await test_sets.create_test_document(
                test_set_id=test_set.id,
                filename="one.txt",
                mime_type="text/plain",
                storage_path=f"test_sets/{test_set.id}/one.txt",
                size_bytes=4,
                page_count=1,
            )
            run, results = await evaluations.create_run_with_results(
                test_set_id=test_set.id,
                workflow_id="wf_serial",
                workflow_version=1,
                workflow_snapshot_json=None,
                name=None,
                total_documents=1,
                document_ids=[document.id],
                workspace_id="ws_serial",
            )
            assert results[0].task_run_id is None
            assert await dispatch.list_for_run(run.id) == []
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_queue_creation_rolls_back_all_rows_on_result_constraint_failure(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine = await _build_repositories(tmp_path)
        try:
            test_set = await test_sets.create_test_set(
                name="Rollback set", description=None, workspace_id="ws_rollback"
            )
            document = await test_sets.create_test_document(
                test_set_id=test_set.id,
                filename="one.txt",
                mime_type="text/plain",
                storage_path=f"test_sets/{test_set.id}/one.txt",
                size_bytes=4,
                page_count=1,
            )
            with pytest.raises(IntegrityError):
                await evaluations.create_run_with_results(
                    test_set_id=test_set.id,
                    workflow_id="wf_rollback",
                    workflow_version=1,
                    workflow_snapshot_json=None,
                    name=None,
                    total_documents=2,
                    document_ids=[document.id, document.id],
                    workspace_id="ws_rollback",
                    queue_mode=True,
                )

            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)  # type: ignore[arg-type]
            async with session_factory() as session:
                assert await session.scalar(select(func.count(EvaluationRun.id))) == 0
                assert await session.scalar(select(func.count(TaskRun.id))) == 0
                assert await session.scalar(select(func.count(EvaluationResult.id))) == 0
                assert await session.scalar(select(func.count(EvaluationDispatchOutbox.id))) == 0
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_claim_failure_backoff_recovery_and_success_are_conditional(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine, payload = await _create_queue_run(tmp_path)
        _run_record, result = payload
        try:
            rows = await dispatch.claim_pending(lease_seconds=30)
            assert len(rows) == 1
            claimed = rows[0]
            assert claimed.status == DISPATCH_PUBLISHING
            assert claimed.attempt_count == 1
            assert await dispatch.claim_pending() == []

            failed_at = claimed.updated_at
            failed = await dispatch.mark_publish_failed(
                claimed.id,
                error="Redis unavailable",
                retry_delay_seconds=10,
                failed_at=failed_at,
            )
            assert failed is not None
            assert failed.status == DISPATCH_PENDING
            assert failed.last_error == "Redis unavailable"
            assert await dispatch.claim_pending(now=failed_at) == []

            retry_rows = await dispatch.claim_pending(
                now=failed_at + timedelta(seconds=10),
            )
            assert len(retry_rows) == 1
            assert retry_rows[0].attempt_count == 2
            published = await dispatch.mark_published(retry_rows[0].id, published_at=failed_at)
            assert published is not None
            assert published.status == DISPATCH_PUBLISHED
            assert (
                await dispatch.mark_publish_failed(
                    retry_rows[0].id,
                    error="late failure",
                    retry_delay_seconds=1,
                    failed_at=failed_at,
                )
                is None
            )
            assert (await dispatch.get_for_result(result.id)).status == DISPATCH_PUBLISHED  # type: ignore[union-attr]
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_expired_publishing_lease_is_reclaimed(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine, _payload = await _create_queue_run(tmp_path)
        try:
            claimed_at = datetime.now()
            claimed = (await dispatch.claim_pending(lease_seconds=30, now=claimed_at))[0]
            assert await dispatch.has_eligible_work(now=claimed_at) is False
            assert (
                await dispatch.recover_expired_leases(now=claimed_at + timedelta(seconds=31)) == 1
            )
            assert await dispatch.has_eligible_work(now=claimed_at + timedelta(seconds=31))
            assert await dispatch.next_available_at() == claimed_at + timedelta(seconds=31)
            recovered = (
                await dispatch.claim_pending(
                    now=claimed_at + timedelta(seconds=31),
                )
            )[0]
            assert recovered.id == claimed.id
            assert recovered.attempt_count == 2
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_cancel_for_run_cancels_unpublished_rows(tmp_path: Path) -> None:
    async def _run() -> None:
        test_sets, evaluations, dispatch, engine, payload = await _create_queue_run(tmp_path)
        run, result = payload
        try:
            claimed = (await dispatch.claim_pending())[0]
            cancelled = await dispatch.cancel_for_run(run.id)
            assert cancelled == 1
            row = await dispatch.get_for_result(result.id)
            assert row is not None
            assert row.status == DISPATCH_CANCELLED
            assert row.lease_expires_at is None
            assert await dispatch.mark_published(claimed.id) is None
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_distributed_uniqueness_rejects_active_duplicate_and_result_duplicate(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        test_sets, evaluations, _dispatch, engine = await _build_repositories(tmp_path)
        try:
            test_set = await test_sets.create_test_set(
                name="Unique set", description=None, workspace_id="ws_unique"
            )
            document = await test_sets.create_test_document(
                test_set_id=test_set.id,
                filename="one.txt",
                mime_type="text/plain",
                storage_path=f"test_sets/{test_set.id}/one.txt",
                size_bytes=4,
                page_count=1,
            )
            first_run = await evaluations.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_unique",
                workflow_version=1,
                workflow_snapshot_json=None,
                name=None,
                total_documents=1,
                client_request_id="request-unique",
                workspace_id="ws_unique",
            )
            with pytest.raises(IntegrityError):
                await evaluations.create_run(
                    test_set_id=test_set.id,
                    workflow_id="wf_unique",
                    workflow_version=1,
                    workflow_snapshot_json=None,
                    name=None,
                    total_documents=1,
                    client_request_id="request-other",
                    workspace_id="ws_unique",
                )

            await evaluations.update_run(
                first_run.id,
                status="completed",
                completed_count=1,
                failed_count=0,
                duration_ms=1,
                workspace_id="ws_unique",
            )
            with pytest.raises(IntegrityError):
                await evaluations.create_run(
                    test_set_id=test_set.id,
                    workflow_id="wf_unique",
                    workflow_version=1,
                    workflow_snapshot_json=None,
                    name=None,
                    total_documents=1,
                    client_request_id="request-unique",
                    workspace_id="ws_unique",
                )

            run = await evaluations.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_unique",
                workflow_version=1,
                workflow_snapshot_json=None,
                name=None,
                total_documents=1,
                client_request_id="request-final",
                workspace_id="ws_unique",
            )
            first_result = await evaluations.create_result(
                evaluation_run_id=run.id,
                document_id=document.id,
                task_run_id="task-one",
                status="queued",
            )
            assert first_result.document_id == document.id
            with pytest.raises(IntegrityError):
                await evaluations.create_result(
                    evaluation_run_id=run.id,
                    document_id=document.id,
                    task_run_id="task-two",
                    status="queued",
                )

            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)  # type: ignore[arg-type]
            async with session_factory() as session:
                assert await session.scalar(select(func.count(EvaluationRun.id))) == 2
        finally:
            await engine.dispose()

    asyncio.run(_run())


async def _load_task(engine: object, task_id: str) -> TaskRun | None:
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)  # type: ignore[arg-type]
    async with session_factory() as session:
        return await session.scalar(select(TaskRun).where(TaskRun.id == task_id))
