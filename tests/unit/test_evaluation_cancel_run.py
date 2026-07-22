from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.db.evaluation_dispatch_outbox import (
    DISPATCH_CANCELLED,
    EvaluationDispatchOutbox,
)
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.test_set_repository import TestSetRepository


async def _build_repositories(
    tmp_path: Path,
) -> tuple[
    TestSetRepository,
    EvaluationRepository,
    EvaluationDispatchRepository,
    async_sessionmaker[Any],
]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evaluation.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return (
        TestSetRepository(session_factory=session_factory),
        EvaluationRepository(session_factory=session_factory),
        EvaluationDispatchRepository(session_factory=session_factory),
        session_factory,
    )


async def _seed_run_with_outbox(
    tmp_path: Path,
    *,
    document_count: int = 2,
    publish_first: bool = False,
    workspace_id: str = "ws_evaluation",
) -> tuple[
    EvaluationRepository,
    EvaluationDispatchRepository,
    async_sessionmaker[Any],
    EvaluationRun,
    list[EvaluationResult],
    list[EvaluationDispatchOutbox],
]:
    test_sets, evaluations, dispatch, session_factory = await _build_repositories(tmp_path)
    test_set = await test_sets.create_test_set(
        name="Evaluation set",
        description=None,
        workspace_id=workspace_id,
    )
    document_ids: list[str] = []
    for index in range(document_count):
        document = await test_sets.create_test_document(
            test_set_id=test_set.id,
            filename=f"doc-{index}.txt",
            mime_type="text/plain",
            storage_path=f"test_sets/{test_set.id}/doc-{index}.txt",
            size_bytes=4,
            page_count=1,
        )
        document_ids.append(document.id)
    run, results = await evaluations.create_run_with_results(
        test_set_id=test_set.id,
        workflow_id="wf_evaluation",
        workflow_version=1,
        workflow_snapshot_json={"nodes": [], "connections": []},
        name="Evaluation run",
        total_documents=document_count,
        document_ids=document_ids,
        workspace_id=workspace_id,
        queue_mode=True,
    )
    outbox_rows = await dispatch.list_for_run(run.id)
    if publish_first:
        for _row in outbox_rows[:1]:
            claimed = await dispatch.claim_pending(limit=1, lease_seconds=30)
            assert claimed
            await dispatch.mark_published(claimed[0].id)
        outbox_rows = await dispatch.list_for_run(run.id)
    return evaluations, dispatch, session_factory, run, results, outbox_rows


def test_cancel_run_marks_run_cancelled_and_skips_nonterminal_results(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, dispatch, sf, run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=2
        )
        cancellation = await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")
        assert cancellation is not None
        assert cancellation.already_cancelled is False
        assert cancellation.published_task_ids == []

        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            assert stored_run is not None
            assert stored_run.status == "cancelled"
            assert stored_run.completed_at is not None

            stored_results = (
                await session.scalars(
                    select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run_obj.id)
                )
            ).all()
            assert all(r.status == "skipped" for r in stored_results)

            stored_outbox = (
                await session.scalars(
                    select(EvaluationDispatchOutbox)
                    .join(
                        EvaluationResult,
                        EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
                    )
                    .where(EvaluationResult.evaluation_run_id == run_obj.id)
                )
            ).all()
            assert all(o.status == DISPATCH_CANCELLED for o in stored_outbox)

    asyncio.run(_run())


def test_cancel_run_returns_published_task_ids_for_revocation(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, _sf, run_obj, _results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=2, publish_first=True
        )
        cancellation = await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")
        assert cancellation is not None
        assert len(cancellation.published_task_ids) == 1

    asyncio.run(_run())


def test_cancel_run_is_idempotent_for_already_cancelled_run(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, _sf, run_obj, _results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=1, publish_first=True
        )
        first = await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")
        assert first is not None
        assert first.already_cancelled is False
        second = await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")
        assert second is not None
        assert second.already_cancelled is True
        assert second.published_task_ids == first.published_task_ids

    asyncio.run(_run())


def test_cancel_run_rejects_terminal_completed_run(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, sf, run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=1
        )
        await evaluations.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="done",
            output_format="ocr",
            processing_time_ms=10,
            error=None,
            task_run_results=[{"result_id": "res_001", "content": "done"}],
            task_run_node_summary={"total": 1, "completed": 1, "failed": 0},
            task_run_result_preview="done",
        )
        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            assert stored_run is not None
            assert stored_run.status == "completed"

        result = await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")
        assert result is None

    asyncio.run(_run())


def test_cancel_run_returns_none_for_missing_run(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, _sf = await _build_repositories(tmp_path)
        result = await evaluations.cancel_run("eval_run_missing", workspace_id="ws_evaluation")
        assert result is None

    asyncio.run(_run())


def test_cancel_run_rejects_cross_workspace_access(tmp_path: Path) -> None:
    async def _run() -> None:
        _evaluations, _dispatch, _sf, run_obj, _results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=1, workspace_id="ws_a"
        )
        result = await _evaluations.cancel_run(run_obj.id, workspace_id="ws_b")
        assert result is None

    asyncio.run(_run())


def test_finalize_result_after_cancel_preserves_cancelled_state(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, sf, run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=1, publish_first=True
        )
        await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")

        late_summary = await evaluations.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="late",
            output_format="ocr",
            processing_time_ms=99,
            error=None,
            task_run_results=[{"result_id": "res_late", "content": "late"}],
            task_run_node_summary={"total": 1, "completed": 1, "failed": 0},
            task_run_result_preview="late",
        )
        assert late_summary is not None
        assert late_summary["sticky_cancelled"] is True
        assert late_summary["result_status"] == "skipped"
        assert late_summary["run_status"] == "cancelled"

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.status == "skipped"
            assert stored_result.output_content is None

    asyncio.run(_run())


def test_late_serial_style_updates_do_not_revive_cancelled_run(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, sf, run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path,
            document_count=1,
        )
        await evaluations.cancel_run(run_obj.id, workspace_id="ws_evaluation")

        updated_result = await evaluations.update_result(
            results[0].id,
            task_run_id=results[0].task_run_id,
            status="completed",
            output_content="late serial output",
            output_format="markdown",
            processing_time_ms=50,
            error=None,
            workspace_id="ws_evaluation",
        )
        updated_run = await evaluations.update_run(
            run_obj.id,
            status="completed",
            completed_count=1,
            failed_count=0,
            duration_ms=50,
            workspace_id="ws_evaluation",
        )

        assert updated_result is not None
        assert updated_result.status == "skipped"
        assert updated_result.output_content is None
        assert updated_run is not None
        assert updated_run.status == "cancelled"

        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_run is not None and stored_run.status == "cancelled"
            assert stored_result is not None and stored_result.status == "skipped"

    asyncio.run(_run())


def test_comparison_summary_counts_matched_and_mismatched_results(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, _sf, run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path, document_count=2
        )
        await evaluations.update_result_comparison_status(
            results[0].id,
            comparison_status="matched",
            workspace_id="ws_evaluation",
        )
        await evaluations.update_result_comparison_status(
            results[1].id,
            comparison_status="mismatched",
            workspace_id="ws_evaluation",
        )

        assert await evaluations.get_comparison_summary_for_run(
            run_obj.id,
            workspace_id="ws_evaluation",
        ) == {"matched": 1, "mismatched": 1}

    asyncio.run(_run())


def test_task_run_lookup_is_document_and_workspace_scoped(tmp_path: Path) -> None:
    async def _run() -> None:
        evaluations, _dispatch, _sf, _run_obj, results, _outbox = await _seed_run_with_outbox(
            tmp_path,
            document_count=1,
            workspace_id="ws_source",
        )
        task_run_id = results[0].task_run_id
        assert task_run_id is not None

        source_result = await evaluations.get_result_for_task_run(
            task_run_id,
            workspace_id="ws_source",
        )
        hidden_result = await evaluations.get_result_for_task_run(
            task_run_id,
            workspace_id="ws_other",
        )

        assert source_result is not None
        assert source_result.document_id == results[0].document_id
        assert hidden_result is None

    asyncio.run(_run())
