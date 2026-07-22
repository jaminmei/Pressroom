from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.test_set_repository import TestSetRepository

WORKSPACE_ID = "ws_evaluation_repository"


async def _build_repositories(tmp_path: Path) -> tuple[TestSetRepository, EvaluationRepository]:
    db_path = tmp_path / "evaluation_repository.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    test_set_repository = TestSetRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    test_set_repository._test_engine = engine  # type: ignore[attr-defined]
    evaluation_repository._test_engine = engine  # type: ignore[attr-defined]
    return test_set_repository, evaluation_repository


def test_create_run_and_result_round_trip(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Eval Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            assert test_set.workspace_id == WORKSPACE_ID
            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="receipt.png",
                mime_type="image/png",
                storage_path=f"test_sets/{test_set.id}/documents/doc_eval_receipt.png",
                size_bytes=321,
                page_count=1,
            )

            run = await evaluation_repo.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_eval_001",
                workflow_version=5,
                workflow_snapshot_json={"nodes": [], "connections": []},
                name="Smoke evaluation",
                total_documents=1,
                workspace_id=WORKSPACE_ID,
            )

            assert run.id.startswith("eval_run_")
            assert run.status == "pending"

            result = await evaluation_repo.create_result(
                evaluation_run_id=run.id,
                document_id=document.id,
                task_run_id=None,
                status="pending",
            )
            assert result.id.startswith("eval_result_")

            updated = await evaluation_repo.update_result(
                result.id,
                task_run_id="task_eval_001",
                status="completed",
                output_content="# done",
                output_format="markdown",
                processing_time_ms=1234,
                error=None,
                workspace_id=WORKSPACE_ID,
            )
            assert updated is not None
            assert updated.task_run_id == "task_eval_001"
            assert updated.output_content == "# done"

            results = await evaluation_repo.list_results(run.id, workspace_id=WORKSPACE_ID)
            assert [item.id for item in results] == [result.id]
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_get_and_update_run_round_trip(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Eval Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            run = await evaluation_repo.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_eval_002",
                workflow_version=7,
                workflow_snapshot_json={"nodes": ["x"]},
                name="Lifecycle evaluation",
                total_documents=3,
                workspace_id=WORKSPACE_ID,
            )

            fetched = await evaluation_repo.get_run(run.id, workspace_id=WORKSPACE_ID)
            assert fetched is not None
            assert fetched.id == run.id

            updated = await evaluation_repo.update_run(
                run.id,
                status="running",
                completed_count=1,
                failed_count=0,
                duration_ms=200,
                workspace_id=WORKSPACE_ID,
            )
            assert updated is not None
            assert updated.status == "running"
            assert updated.completed_count == 1
            assert updated.duration_ms == 200
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_update_run_persists_started_and_completed_timestamps(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Eval Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            run = await evaluation_repo.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_eval_002",
                workflow_version=7,
                workflow_snapshot_json={"nodes": ["x"]},
                name="Lifecycle evaluation",
                total_documents=3,
                workspace_id=WORKSPACE_ID,
            )

            started_at = run.created_at
            completed_at = run.created_at

            updated = await evaluation_repo.update_run(
                run.id,
                status="completed",
                completed_count=3,
                failed_count=0,
                duration_ms=200,
                started_at=started_at,
                completed_at=completed_at,
                workspace_id=WORKSPACE_ID,
            )
            assert updated is not None
            assert updated.started_at == started_at
            assert updated.completed_at == completed_at
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_get_result_returns_updated_result(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Eval Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="receipt.png",
                mime_type="image/png",
                storage_path=f"test_sets/{test_set.id}/documents/doc_eval_receipt.png",
                size_bytes=321,
                page_count=1,
            )
            run = await evaluation_repo.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_eval_003",
                workflow_version=1,
                workflow_snapshot_json=None,
                name=None,
                total_documents=1,
                workspace_id=WORKSPACE_ID,
            )
            result = await evaluation_repo.create_result(
                evaluation_run_id=run.id,
                document_id=document.id,
                task_run_id=None,
                status="pending",
            )

            fetched = await evaluation_repo.get_result(result.id, workspace_id=WORKSPACE_ID)

            assert fetched is not None
            assert fetched.id == result.id
            assert fetched.status == "pending"
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_result_rejects_duplicate_task_run_id(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Eval Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            first_document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="first.png",
                mime_type="image/png",
                storage_path=f"test_sets/{test_set.id}/documents/doc_first.png",
                size_bytes=111,
                page_count=1,
            )
            second_document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="second.png",
                mime_type="image/png",
                storage_path=f"test_sets/{test_set.id}/documents/doc_second.png",
                size_bytes=222,
                page_count=1,
            )
            run = await evaluation_repo.create_run(
                test_set_id=test_set.id,
                workflow_id="wf_eval_004",
                workflow_version=1,
                workflow_snapshot_json=None,
                name=None,
                total_documents=2,
                workspace_id=WORKSPACE_ID,
            )
            first_result = await evaluation_repo.create_result(
                evaluation_run_id=run.id,
                document_id=first_document.id,
                task_run_id="task_eval_shared",
                status="completed",
            )
            assert first_result.task_run_id == "task_eval_shared"

            with pytest.raises(IntegrityError):
                await evaluation_repo.create_result(
                    evaluation_run_id=run.id,
                    document_id=second_document.id,
                    task_run_id="task_eval_shared",
                    status="completed",
                )
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())
