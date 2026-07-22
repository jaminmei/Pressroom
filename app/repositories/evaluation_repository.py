"""Repository for evaluation runs and results."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.db.evaluation_dispatch_outbox import (
    DISPATCH_PENDING,
    EvaluationDispatchOutbox,
)
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.task_run import TaskRun
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], AsyncSession]


@dataclass(slots=True)
class CancellationResult:
    """Outcome of an evaluation-run cancellation.

    ``run`` is the post-cancel run row. ``published_task_ids`` lists every
    task the caller must revoke at the broker. ``already_cancelled`` is
    True for an idempotent replay of an already-cancelled run.
    """

    run: EvaluationRun
    published_task_ids: list[str]
    already_cancelled: bool


def _run_workspace_clause(workspace_id: str) -> ColumnElement[bool]:
    return EvaluationRun.workspace_id == workspace_id


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EvaluationRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory: SessionFactory = session_factory or cast(
            SessionFactory, AsyncSessionLocal
        )

    async def create_run(
        self,
        *,
        test_set_id: str,
        workflow_id: str,
        workflow_version: int | None,
        workflow_snapshot_json: dict[str, Any] | None,
        name: str | None,
        total_documents: int,
        client_request_id: str | None = None,
        workspace_id: str | None = None,
    ) -> EvaluationRun:
        record = EvaluationRun(
            id=f"eval_run_{uuid4()}",
            name=name,
            test_set_id=test_set_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_snapshot_json=(
                json.dumps(workflow_snapshot_json, ensure_ascii=False)
                if workflow_snapshot_json is not None
                else None
            ),
            client_request_id=client_request_id,
            status="pending",
            total_documents=total_documents,
            completed_count=0,
            failed_count=0,
            created_at=_utcnow_naive(),
        )
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def create_run_with_results(
        self,
        *,
        test_set_id: str,
        workflow_id: str,
        workflow_version: int | None,
        workflow_snapshot_json: dict[str, Any] | None,
        name: str | None,
        total_documents: int,
        client_request_id: str | None = None,
        document_ids: list[str],
        workspace_id: str | None = None,
        queue_mode: bool = False,
    ) -> tuple[EvaluationRun, list[EvaluationResult]]:
        now = _utcnow_naive()
        run = EvaluationRun(
            id=f"eval_run_{uuid4()}",
            name=name,
            test_set_id=test_set_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_snapshot_json=(
                json.dumps(workflow_snapshot_json, ensure_ascii=False)
                if workflow_snapshot_json is not None
                else None
            ),
            client_request_id=client_request_id,
            status="pending",
            total_documents=total_documents,
            completed_count=0,
            failed_count=0,
            created_at=now,
        )
        results = [
            EvaluationResult(
                id=f"eval_result_{uuid4()}",
                evaluation_run_id=run.id,
                document_id=doc_id,
                task_run_id=(f"eval_task_{run.id}_{doc_id}" if queue_mode else None),
                status="queued",
                created_at=now,
            )
            for doc_id in document_ids
        ]
        async with self._session_factory() as session:
            session.add(run)
            await session.flush()

            if queue_mode:
                task_runs = [
                    TaskRun(
                        id=result.task_run_id,
                        status="queued",
                        workflow_id=workflow_id,
                        source="evaluation",
                        workspace_id=workspace_id,
                        evaluation_run_id=run.id,
                        created_at=now,
                        updated_at=now,
                    )
                    for result in results
                    if result.task_run_id is not None
                ]
                session.add_all(task_runs)
                await session.flush()

            session.add_all(results)
            await session.flush()

            if queue_mode:
                dispatch_records = [
                    EvaluationDispatchOutbox(
                        id=f"eval_dispatch_{uuid4()}",
                        evaluation_result_id=result.id,
                        task_run_id=result.task_run_id,
                        status=DISPATCH_PENDING,
                        attempt_count=0,
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    for result in results
                    if result.task_run_id is not None
                ]
                session.add_all(dispatch_records)

            await session.commit()
            await session.refresh(run)
            for result in results:
                await session.refresh(result)
            return run, results

    async def get_run(
        self,
        run_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> EvaluationRun | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = select(EvaluationRun).where(EvaluationRun.id == run_id)
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            if record is None:
                return None
            if (
                expected_workspace_id is not None
                and record.workspace_id is not None
                and record.workspace_id != expected_workspace_id
            ):
                return None
            return record

    async def get_active_run_for_test_set(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> EvaluationRun | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationRun)
            .where(EvaluationRun.test_set_id == test_set_id)
            .where(EvaluationRun.status.in_(("pending", "running")))
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return result.first()

    async def update_run(
        self,
        run_id: str,
        *,
        status: str,
        completed_count: int,
        failed_count: int,
        duration_ms: int | None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        workspace_id: str | None = None,
    ) -> EvaluationRun | None:
        workspace_id = _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
            statement = statement.where(_run_workspace_clause(workspace_id))
            record = await session.scalar(statement)
            if record is None:
                return None
            if record.status == "cancelled" and status != "cancelled":
                return record
            record.status = status
            record.completed_count = completed_count
            record.failed_count = failed_count
            record.duration_ms = duration_ms
            record.started_at = started_at
            record.completed_at = completed_at
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def create_result(
        self,
        *,
        evaluation_run_id: str,
        document_id: str,
        task_run_id: str | None,
        status: str,
    ) -> EvaluationResult:
        record = EvaluationResult(
            id=f"eval_result_{uuid4()}",
            evaluation_run_id=evaluation_run_id,
            document_id=document_id,
            task_run_id=task_run_id,
            status=status,
            created_at=_utcnow_naive(),
        )
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_result(
        self,
        result_id: str,
        *,
        workspace_id: str | None = None,
        expected_workspace_id: str | None = None,
    ) -> EvaluationResult | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationResult)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.id == result_id)
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            if record is None:
                return None
            if expected_workspace_id is None:
                return record
            owning_workspace_id = await session.scalar(
                select(EvaluationRun.workspace_id).where(
                    EvaluationRun.id == record.evaluation_run_id
                )
            )
            if owning_workspace_id is not None and owning_workspace_id != expected_workspace_id:
                return None
            return record

    async def get_result_for_task_run(
        self,
        task_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> EvaluationResult | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationResult)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.task_run_id == task_run_id)
            .where(_run_workspace_clause(workspace_id))
        )
        async with self._session_factory() as session:
            record = await session.scalar(statement)
            return record

    async def update_result(
        self,
        result_id: str,
        *,
        task_run_id: str | None,
        status: str,
        output_content: str | None,
        output_format: str | None,
        processing_time_ms: int | None,
        error: str | None,
        workspace_id: str | None = None,
    ) -> EvaluationResult | None:
        workspace_id = _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            run_id = await session.scalar(
                select(EvaluationResult.evaluation_run_id)
                .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
                .where(EvaluationResult.id == result_id)
                .where(_run_workspace_clause(workspace_id))
            )
            if run_id is None:
                return None
            run = await session.scalar(
                select(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .where(_run_workspace_clause(workspace_id))
                .with_for_update()
            )
            if run is None:
                return None
            record = await session.scalar(
                select(EvaluationResult)
                .where(EvaluationResult.id == result_id)
                .where(EvaluationResult.evaluation_run_id == run_id)
                .with_for_update()
            )
            if record is None:
                return None
            record.task_run_id = task_run_id
            if run.status == "cancelled":
                record.status = "skipped"
                record.output_content = None
                record.output_format = None
                record.processing_time_ms = None
                record.error = None
            else:
                record.status = status
                record.output_content = output_content
                record.output_format = output_format
                record.processing_time_ms = processing_time_ms
                record.error = error
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def list_results(
        self,
        evaluation_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[EvaluationResult]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationResult)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def list_runs_for_test_set(
        self,
        test_set_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[EvaluationRun]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationRun)
            .where(EvaluationRun.test_set_id == test_set_id)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        )
        statement = statement.where(EvaluationRun.workspace_id == workspace_id)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def list_document_run_history(
        self,
        *,
        test_set_id: str,
        document_id: str,
        limit: int,
        offset: int,
        workspace_id: str | None = None,
    ) -> tuple[list[tuple[EvaluationResult, EvaluationRun]], int]:
        """Return one document's evaluation history and the unpaged total."""
        workspace_id = _require_workspace_filter(workspace_id)
        filters = (
            EvaluationResult.document_id == document_id,
            EvaluationRun.test_set_id == test_set_id,
            EvaluationRun.workspace_id == workspace_id,
        )
        count_statement = (
            select(func.count(EvaluationResult.id))
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(*filters)
        )
        statement = (
            select(EvaluationResult, EvaluationRun)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(*filters)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._session_factory() as session:
            total = int(await session.scalar(count_statement) or 0)
            rows = (await session.execute(statement)).all()
            return [(row[0], row[1]) for row in rows], total

    async def find_run_by_client_request_id(
        self,
        test_set_id: str,
        client_request_id: str,
        *,
        workspace_id: str | None = None,
    ) -> EvaluationRun | None:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationRun)
            .where(EvaluationRun.test_set_id == test_set_id)
            .where(EvaluationRun.client_request_id == client_request_id)
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return result.first()

    async def list_results_by_review_status(
        self,
        evaluation_run_id: str,
        review_status: str,
        *,
        workspace_id: str | None = None,
    ) -> list[EvaluationResult]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(EvaluationResult)
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .where(EvaluationResult.review_status == review_status)
            .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
        )
        statement = statement.where(EvaluationRun.workspace_id == workspace_id)
        async with self._session_factory() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def update_result_review(
        self,
        result_id: str,
        *,
        review_status: str,
        accepted_ground_truth_id: str | None = None,
        reviewed_at: datetime | None = None,
        reviewed_by: str | None = None,
        review_notes: str | None = None,
        comparison_status: str | None = None,
        workspace_id: str | None = None,
    ) -> EvaluationResult | None:
        workspace_id = _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = (
                select(EvaluationResult)
                .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
                .where(EvaluationResult.id == result_id)
            )
            statement = statement.where(_run_workspace_clause(workspace_id))
            record = await session.scalar(statement)
            if record is None:
                return None
            record.review_status = review_status
            record.accepted_ground_truth_id = accepted_ground_truth_id
            record.reviewed_at = reviewed_at
            record.reviewed_by = reviewed_by
            record.review_notes = review_notes
            if comparison_status is not None:
                record.comparison_status = comparison_status
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def update_result_comparison_status(
        self,
        result_id: str,
        *,
        comparison_status: str,
        workspace_id: str | None = None,
    ) -> EvaluationResult | None:
        workspace_id = _require_workspace_filter(workspace_id)
        async with self._session_factory() as session:
            statement = (
                select(EvaluationResult)
                .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
                .where(EvaluationResult.id == result_id)
            )
            statement = statement.where(_run_workspace_clause(workspace_id))
            record = await session.scalar(statement)
            if record is None:
                return None
            record.comparison_status = comparison_status
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_result_summary_for_run(
        self,
        evaluation_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, int]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(
                EvaluationResult.status,
                func.count(EvaluationResult.id),
            )
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .group_by(EvaluationResult.status)
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            rows = await session.execute(statement)
            return {status: count for status, count in rows.all()}

    async def get_review_summary_for_run(
        self,
        evaluation_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, int]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(
                EvaluationResult.review_status,
                func.count(EvaluationResult.id),
            )
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .group_by(EvaluationResult.review_status)
        )
        statement = statement.where(_run_workspace_clause(workspace_id))
        async with self._session_factory() as session:
            rows = await session.execute(statement)
            return {status: count for status, count in rows.all()}

    async def get_comparison_summary_for_run(
        self,
        evaluation_run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, int]:
        workspace_id = _require_workspace_filter(workspace_id)
        statement = (
            select(
                EvaluationResult.comparison_status,
                func.count(EvaluationResult.id),
            )
            .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .where(_run_workspace_clause(workspace_id))
            .group_by(EvaluationResult.comparison_status)
        )
        async with self._session_factory() as session:
            rows = await session.execute(statement)
            return {status: count for status, count in rows.all() if status is not None}

    async def load_result_for_execution(
        self,
        result_id: str,
    ) -> dict[str, Any] | None:
        """Load the durable snapshot needed to execute one evaluation result.

        Returns ``None`` if the result, run, task run, or workspace is missing
        or inconsistent. Includes the workflow snapshot, document binding,
        placeholder TaskRun id, workspace id, and current terminal state of the
        result and run.
        """
        from app.models.db.test_document import TestDocument

        async with self._session_factory() as session:
            statement = (
                select(EvaluationResult, EvaluationRun, TaskRun)
                .join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
                .outerjoin(TaskRun, TaskRun.id == EvaluationResult.task_run_id)
                .where(EvaluationResult.id == result_id)
            )
            row = (await session.execute(statement)).first()
            if row is None:
                return None
            result, run, task_run = row
            if run.workspace_id is None:
                return None
            workspace_id = run.workspace_id
            if task_run is not None and task_run.workspace_id not in (None, workspace_id):
                return None
            document = await session.scalar(
                select(TestDocument).where(TestDocument.id == result.document_id)
            )
            if document is None:
                return None
            workflow_snapshot = (
                json.loads(run.workflow_snapshot_json) if run.workflow_snapshot_json else None
            )
            return {
                "result_id": result.id,
                "result_status": result.status,
                "run_id": run.id,
                "run_status": run.status,
                "test_set_id": run.test_set_id,
                "workflow_id": run.workflow_id,
                "workflow_version": run.workflow_version,
                "workflow_snapshot": workflow_snapshot,
                "document_id": document.id,
                "document_filename": document.filename,
                "document_mime_type": document.mime_type,
                "document_storage_path": document.storage_path,
                "document_size_bytes": document.size_bytes,
                "task_run_id": result.task_run_id,
                "workspace_id": workspace_id,
            }

    async def mark_result_running(
        self,
        result_id: str,
        *,
        workspace_id: str | None = None,
    ) -> str | None:
        """Atomically mark a non-terminal evaluation result as running.

        The transition is workspace-scoped and cancellation-safe. Terminal
        results and results belonging to terminal runs are never revived.
        When a queue placeholder ``TaskRun`` exists, its status is advanced in
        the same transaction so both execution views remain consistent.

        Returns the effective result status, or ``None`` when the result is not
        visible in the requested workspace.
        """
        workspace_id = _require_workspace_filter(workspace_id)
        terminal_result_statuses = {"completed", "failed", "skipped"}
        terminal_run_statuses = {
            "completed",
            "partial_completed",
            "failed",
            "cancelled",
        }

        async with self._session_factory() as session:
            run_id = await session.scalar(
                select(EvaluationResult.evaluation_run_id)
                .join(
                    EvaluationRun,
                    EvaluationRun.id == EvaluationResult.evaluation_run_id,
                )
                .where(EvaluationResult.id == result_id)
                .where(_run_workspace_clause(workspace_id))
            )
            if run_id is None:
                return None

            run = await session.scalar(
                select(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .where(_run_workspace_clause(workspace_id))
                .with_for_update()
            )
            if run is None:
                return None

            result = await session.scalar(
                select(EvaluationResult)
                .where(EvaluationResult.id == result_id)
                .where(EvaluationResult.evaluation_run_id == run_id)
                .with_for_update()
            )
            if result is None:
                return None
            if result.status in terminal_result_statuses:
                return result.status

            if run.status in terminal_run_statuses:
                if run.status == "cancelled":
                    result.status = "skipped"
                    session.add(result)
                    await session.commit()
                    return "skipped"
                return result.status

            result.status = "running"
            session.add(result)

            if result.task_run_id is not None:
                task_run = await session.scalar(
                    select(TaskRun).where(TaskRun.id == result.task_run_id).with_for_update()
                )
                if task_run is not None and task_run.status not in terminal_run_statuses:
                    task_run.status = "running"
                    task_run.updated_at = _utcnow_naive()
                    session.add(task_run)

            await session.commit()
            return "running"

    async def finalize_result(
        self,
        result_id: str,
        *,
        outcome_status: str,
        output_content: str | None,
        output_format: str | None,
        processing_time_ms: int | None,
        error: str | None,
        task_run_results: list[dict[str, Any]] | None,
        task_run_node_summary: dict[str, int] | None,
        task_run_result_preview: str | None,
    ) -> dict[str, Any] | None:
        """Atomically finalize one result and reconcile its run.

        Updates the EvaluationResult, TaskRun snapshot (when present), and
        EvaluationRun counters / terminal status under a run-row lock.
        ``cancelled`` is sticky: a late worker completion cannot restore a
        non-cancelled run, and its result is forced to ``skipped``.

        Returns a summary dict with the post-finalization run state, or
        ``None`` if the result or run could not be found.
        """
        async with self._session_factory() as session:
            statement = (
                select(EvaluationResult).where(EvaluationResult.id == result_id).with_for_update()
            )
            result = await session.scalar(statement)
            if result is None:
                return None
            run_id = result.evaluation_run_id
            task_run_id = result.task_run_id

            run_statement = (
                select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
            )
            run = await session.scalar(run_statement)
            if run is None:
                return None

            # Sticky cancellation: late worker output must not flip a cancelled
            # run back to running, and the result becomes skipped.
            sticky_cancelled = run.status == "cancelled"
            effective_outcome = "skipped" if sticky_cancelled else outcome_status

            result.status = effective_outcome
            result.output_content = None if sticky_cancelled else output_content
            result.output_format = None if sticky_cancelled else output_format
            result.processing_time_ms = None if sticky_cancelled else processing_time_ms
            result.error = None if sticky_cancelled else error
            session.add(result)

            if task_run_id is not None and task_run_results is not None:
                existing_task = await session.scalar(
                    select(TaskRun).where(TaskRun.id == task_run_id)
                )
                if existing_task is not None:
                    existing_task.status = effective_outcome
                    if task_run_results is not None:
                        existing_task.results_json = json.dumps(
                            task_run_results, ensure_ascii=False
                        )
                    if task_run_node_summary is not None:
                        existing_task.node_summary_json = json.dumps(task_run_node_summary)
                    if task_run_result_preview is not None:
                        existing_task.result_preview = task_run_result_preview
                    if error is not None and not sticky_cancelled:
                        existing_task.error = error
                    existing_task.updated_at = _utcnow_naive()
                    session.add(existing_task)

            await session.flush()

            counts_statement = (
                select(EvaluationResult.status, func.count(EvaluationResult.id))
                .where(EvaluationResult.evaluation_run_id == run_id)
                .group_by(EvaluationResult.status)
            )
            counts_rows = await session.execute(counts_statement)
            counts_by_status: dict[str, int] = {
                status: count for status, count in counts_rows.all()
            }
            completed_count = int(counts_by_status.get("completed", 0))
            failed_count = int(counts_by_status.get("failed", 0))
            skipped_count = int(counts_by_status.get("skipped", 0))
            total = run.total_documents

            now = _utcnow_naive()
            if sticky_cancelled:
                new_status = "cancelled"
            elif completed_count + failed_count + skipped_count >= total:
                if failed_count == 0 and skipped_count == 0:
                    new_status = "completed"
                elif completed_count == 0 and skipped_count == 0:
                    new_status = "failed"
                else:
                    new_status = "partial_completed"
            else:
                new_status = "running"

            if run.started_at is None and effective_outcome in (
                "completed",
                "failed",
                "skipped",
            ):
                run.started_at = now
            if new_status in ("completed", "partial_completed", "failed", "cancelled"):
                run.completed_at = run.completed_at or now
                if run.duration_ms is None and run.started_at is not None:
                    run.duration_ms = max(
                        int((run.completed_at - run.started_at).total_seconds() * 1000),
                        0,
                    )
            run.status = new_status
            run.completed_count = completed_count
            run.failed_count = failed_count
            session.add(run)

            await session.commit()
            await session.refresh(run)
            await session.refresh(result)
            return {
                "run_id": run.id,
                "run_status": run.status,
                "completed_count": run.completed_count,
                "failed_count": run.failed_count,
                "result_status": result.status,
                "sticky_cancelled": sticky_cancelled,
            }

    async def cancel_run(
        self,
        run_id: str,
        *,
        workspace_id: str | None = None,
    ) -> CancellationResult | None:
        """Atomically cancel a non-terminal run.

        Marks the run as ``cancelled``, marks every non-terminal result as
        ``skipped``, and cancels every pending/publishing outbox row. Returns
        ``None`` if the run is missing, in a different workspace, or already
        in a terminal state other than ``cancelled`` (idempotent replay).
        The returned ``CancellationResult`` carries the post-cancel run row
        and the list of task IDs whose Celery messages were already
        published (and therefore must be revoked at the broker by the
        caller). The published-task-id list is collected both inside the
        cancellation transaction and re-read after commit so that a
        publisher racing the canceller cannot escape revocation.

        A session-level advisory lock on ``run_id`` is held across both the
        transaction and the post-commit re-SELECT so a publisher holding
        the same lock cannot publish between commit and re-SELECT.
        """
        from sqlalchemy import text as sa_text

        from app.db.session import AsyncSessionLocal
        from app.db.session import engine as async_engine
        from app.models.db.evaluation_dispatch_outbox import (
            DISPATCH_PENDING,
            DISPATCH_PUBLISHED,
            DISPATCH_PUBLISHING,
            EvaluationDispatchOutbox,
        )

        workspace_id = _require_workspace_filter(workspace_id)

        dialect_name = ""
        try:
            raw_engine = async_engine.sync_engine
            if hasattr(raw_engine, "dialect"):
                dialect_name = raw_engine.dialect.name
        except Exception:  # noqa: BLE001
            dialect_name = ""

        published_select_statement = (
            select(EvaluationDispatchOutbox.task_run_id)
            .join(
                EvaluationResult,
                EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
            )
            .where(EvaluationResult.evaluation_run_id == run_id)
            .where(EvaluationDispatchOutbox.status == DISPATCH_PUBLISHED)
        )

        lock_session = None
        if dialect_name == "postgresql":
            lock_session = AsyncSessionLocal()
            await lock_session.execute(
                sa_text("SELECT pg_advisory_lock(hashtext(:rid))"), {"rid": run_id}
            )
            await lock_session.commit()

        try:
            async with self._session_factory() as session:
                run_statement = (
                    select(EvaluationRun)
                    .where(EvaluationRun.id == run_id)
                    .where(_run_workspace_clause(workspace_id))
                    .with_for_update()
                )
                run = await session.scalar(run_statement)
                if run is None:
                    return None

                if run.status == "cancelled":
                    in_txn_published = list(
                        (await session.execute(published_select_statement)).scalars().all()
                    )
                    return CancellationResult(
                        run=run,
                        published_task_ids=in_txn_published,
                        already_cancelled=True,
                    )

                if run.status in ("completed", "partial_completed", "failed"):
                    return None

                results_statement = (
                    select(EvaluationResult)
                    .where(EvaluationResult.evaluation_run_id == run_id)
                    .with_for_update()
                )
                nonterminal_results = (await session.scalars(results_statement)).all()
                for result in nonterminal_results:
                    if result.status not in ("completed", "failed", "skipped"):
                        result.status = "skipped"
                        session.add(result)

                outbox_statement = (
                    select(EvaluationDispatchOutbox)
                    .join(
                        EvaluationResult,
                        EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
                    )
                    .where(EvaluationResult.evaluation_run_id == run_id)
                    .where(
                        EvaluationDispatchOutbox.status.in_((DISPATCH_PENDING, DISPATCH_PUBLISHING))
                    )
                    .with_for_update(skip_locked=True)
                )
                cancelled_outbox_rows = (await session.scalars(outbox_statement)).all()
                for outbox in cancelled_outbox_rows:
                    outbox.status = "cancelled"
                    outbox.lease_expires_at = None
                    session.add(outbox)

                in_txn_published = list(
                    (await session.execute(published_select_statement)).scalars().all()
                )

                now = _utcnow_naive()
                run.status = "cancelled"
                run.started_at = run.started_at or now
                run.completed_at = run.completed_at or now
                if run.duration_ms is None and run.started_at is not None:
                    run.duration_ms = max(
                        int((run.completed_at - run.started_at).total_seconds() * 1000),
                        0,
                    )
                session.add(run)

                await session.commit()
                await session.refresh(run)

            post_commit_published = await self._collect_published_task_ids(run_id)
            final_published = list(dict.fromkeys(in_txn_published + post_commit_published))
            return CancellationResult(
                run=run,
                published_task_ids=final_published,
                already_cancelled=False,
            )
        finally:
            if lock_session is not None:
                try:
                    await lock_session.execute(
                        sa_text("SELECT pg_advisory_unlock(hashtext(:rid))"),
                        {"rid": run_id},
                    )
                    await lock_session.commit()
                except Exception:  # noqa: BLE001 — unlock failure must not mask the real result
                    pass
                finally:
                    await lock_session.close()

    async def _collect_published_task_ids(self, run_id: str) -> list[str]:
        from app.models.db.evaluation_dispatch_outbox import (
            DISPATCH_PUBLISHED,
            EvaluationDispatchOutbox,
        )

        statement = (
            select(EvaluationDispatchOutbox.task_run_id)
            .join(
                EvaluationResult,
                EvaluationResult.id == EvaluationDispatchOutbox.evaluation_result_id,
            )
            .where(EvaluationResult.evaluation_run_id == run_id)
            .where(EvaluationDispatchOutbox.status == DISPATCH_PUBLISHED)
        )
        async with self._session_factory() as session:
            return list((await session.execute(statement)).scalars().all())
