from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.api.task_helpers import collect_results_from_snapshot, extract_final_output_from_context
from app.config import get_settings
from app.core.feature_flags import FeatureFlags, OrchestratorMode
from app.errors import AppError, ErrorCode
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition
from app.repositories.evaluation_repository import CancellationResult, EvaluationRepository
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.task_run_repository import TaskRunRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.task_orchestrator import TaskOrchestrator

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchCounts:
    completed: int = 0
    failed: int = 0
    duration_ms: int = 0


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EvaluationService:
    def __init__(
        self,
        *,
        orchestrator: TaskOrchestrator,
        test_set_repository: TestSetRepository | None = None,
        evaluation_repository: EvaluationRepository | None = None,
        ground_truth_repository: GroundTruthRepository | None = None,
        task_run_repository: TaskRunRepository | None = None,
        completion_timeout: float = 300.0,
    ) -> None:
        self._orchestrator = orchestrator
        self._test_set_repository = test_set_repository or TestSetRepository()
        self._evaluation_repository = evaluation_repository or EvaluationRepository()
        self._ground_truth_repository = ground_truth_repository or GroundTruthRepository()
        self._task_run_repository = task_run_repository or TaskRunRepository()
        self._completion_timeout = completion_timeout

    async def run_batch(
        self,
        *,
        run_id: str,
        test_set_id: str,
        workflow: WorkflowDefinition,
        orchestrator_mode: OrchestratorMode | None = None,
        workspace_id: str | None = None,
    ) -> None:
        active_mode = orchestrator_mode or FeatureFlags.get_orchestrator_mode()
        if active_mode == OrchestratorMode.QUEUE:
            raise RuntimeError("Evaluation batch execution requires serial orchestrator mode")

        pre_created_results = await self._evaluation_repository.list_results(
            run_id,
            workspace_id=workspace_id,
        )
        counts = BatchCounts()
        started_at = _utcnow_naive()

        await self._evaluation_repository.update_run(
            run_id,
            status="running",
            completed_count=counts.completed,
            failed_count=counts.failed,
            duration_ms=counts.duration_ms or None,
            started_at=started_at,
            completed_at=None,
            workspace_id=workspace_id,
        )

        for result in pre_created_results:
            document = await self._test_set_repository.get_test_document(
                result.document_id,
                workspace_id=workspace_id,
                expected_workspace_id=workspace_id,
            )
            if document is None:
                counts.failed += 1
                await self._evaluation_repository.update_result(
                    result.id,
                    task_run_id=None,
                    status="failed",
                    output_content=None,
                    output_format=None,
                    processing_time_ms=None,
                    error=f"Document not found: {result.document_id}",
                    workspace_id=workspace_id,
                )
                await self._evaluation_repository.update_run(
                    run_id,
                    status="running",
                    completed_count=counts.completed,
                    failed_count=counts.failed,
                    duration_ms=counts.duration_ms or None,
                    started_at=started_at,
                    completed_at=None,
                    workspace_id=workspace_id,
                )
                continue

            input_node_id = next(
                (n.id for n in workflow.nodes if n.type.startswith("input/")),
                "input_1",
            )
            created_context = None

            execution_status = await self._evaluation_repository.mark_result_running(
                result.id,
                workspace_id=workspace_id,
            )
            if execution_status != "running":
                if execution_status == "completed":
                    counts.completed += 1
                    continue
                if execution_status == "failed":
                    counts.failed += 1
                    continue
                # A skipped or otherwise non-runnable result means the run was
                # cancelled or reached a terminal state while the batch was active.
                return

            try:
                created_context = await self._orchestrator.create_from_workflow(
                    workflow,
                    input_bindings={
                        input_node_id: TaskInputFile(
                            file_path=str(
                                Path(get_settings().storage_root) / document.storage_path
                            ),
                            filename=document.filename,
                            mime_type=document.mime_type,
                            size_bytes=document.size_bytes,
                        )
                    },
                    source="evaluation",
                    evaluation_run_id=run_id,
                    workspace_id=workspace_id,
                )
                completed_context = await self._orchestrator.wait_for_completion(
                    created_context.task_id,
                    timeout=self._completion_timeout,
                    workspace_id=workspace_id,
                )
                output_content, output_format = extract_final_output_from_context(completed_context)
                processing_time_ms = completed_context.duration_ms
                counts.completed += 1
                if isinstance(processing_time_ms, int) and processing_time_ms > 0:
                    counts.duration_ms += processing_time_ms
                await self._evaluation_repository.update_result(
                    result.id,
                    task_run_id=created_context.task_id,
                    status="completed",
                    output_content=output_content,
                    output_format=output_format,
                    processing_time_ms=processing_time_ms,
                    error=None,
                    workspace_id=workspace_id,
                )
            except Exception as exc:  # noqa: BLE001
                counts.failed += 1
                await self._evaluation_repository.update_result(
                    result.id,
                    task_run_id=created_context.task_id if created_context else None,
                    status="failed",
                    output_content=None,
                    output_format=None,
                    processing_time_ms=None,
                    error=str(exc),
                    workspace_id=workspace_id,
                )

            await self._evaluation_repository.update_run(
                run_id,
                status="running",
                completed_count=counts.completed,
                failed_count=counts.failed,
                duration_ms=counts.duration_ms or None,
                started_at=started_at,
                completed_at=None,
                workspace_id=workspace_id,
            )

        await self._evaluation_repository.update_run(
            run_id,
            status="failed" if counts.completed == 0 and counts.failed > 0 else "completed",
            completed_count=counts.completed,
            failed_count=counts.failed,
            duration_ms=counts.duration_ms or None,
            started_at=started_at,
            completed_at=_utcnow_naive(),
            workspace_id=workspace_id,
        )

    async def cancel_run(
        self,
        run_id: str,
        *,
        workspace_id: str,
    ) -> CancellationResult | None:
        """Cancel an evaluation run and revoke its published Celery tasks.

        Delegates the durable state mutation to ``EvaluationRepository.cancel_run``
        and best-effort revokes every published task ID at the broker. Returns
        the ``CancellationResult`` (or ``None`` if the run is missing, in a
        different workspace, or already in a terminal state other than
        ``cancelled``).
        """
        cancellation = await self._evaluation_repository.cancel_run(
            run_id, workspace_id=workspace_id
        )
        if cancellation is None:
            return None

        if cancellation.published_task_ids:
            try:
                from app.worker import celery_app
            except ImportError:
                celery_app = None

            if celery_app is not None:
                for task_id in cancellation.published_task_ids:
                    try:
                        celery_app.control.revoke(task_id, terminate=False)
                    except Exception as exc:  # noqa: BLE001 — keep cancellation durable
                        logger.warning(
                            "Failed to revoke Celery task %s during run %s cancellation "
                            "error_type=%s",
                            task_id,
                            run_id,
                            type(exc).__name__,
                        )
        return cancellation

    async def apply_result_as_ground_truth(
        self,
        *,
        document_id: str,
        task_run_id: str,
        notes: str | None,
        workspace_id: str,
        requested_by_user_id: str,
    ) -> Any:
        source_result = await self._evaluation_repository.get_result_for_task_run(
            task_run_id,
            workspace_id=workspace_id,
        )
        if source_result is None or source_result.document_id != document_id:
            raise AppError(
                ErrorCode.TASK_NOT_FOUND,
                f"Task run not found for document {document_id}: {task_run_id}",
            )

        try:
            context = await self._orchestrator.wait_for_completion(
                task_run_id,
                timeout=self._completion_timeout,
                workspace_id=workspace_id,
            )
        except KeyError:
            context = None

        if context is not None:
            context_owner = getattr(context, "requested_by_user_id", None)
            if context_owner is not None and context_owner != requested_by_user_id:
                raise AppError(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task run not found: {task_run_id}",
                )
            try:
                content, output_format = extract_final_output_from_context(context)
            except ValueError:
                content, output_format = await self._extract_output_from_snapshot(
                    task_run_id,
                    workspace_id=workspace_id,
                    task_exists=True,
                )
        else:
            content, output_format = await self._extract_output_from_snapshot(
                task_run_id,
                workspace_id=workspace_id,
                task_exists=False,
            )

        return await self._ground_truth_repository.create_version(
            document_id=document_id,
            source="inference_apply",
            format=output_format,
            content=content,
            source_task_run_id=task_run_id,
            notes=notes,
            workspace_id=workspace_id,
        )

    async def _extract_output_from_snapshot(
        self,
        task_run_id: str,
        *,
        workspace_id: str,
        task_exists: bool,
    ) -> tuple[str, str]:
        snapshot = await self._task_run_repository.get_snapshot(
            task_run_id,
            workspace_id=workspace_id,
            expected_workspace_id=workspace_id,
        )
        if snapshot is None:
            if not task_exists:
                raise AppError(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task run not found: {task_run_id}",
                )
            raise AppError(
                ErrorCode.TASK_RESULT_NOT_READY,
                f"Task run has no output result yet: {task_run_id}",
            )
        if not snapshot.results:
            raise AppError(
                ErrorCode.TASK_RESULT_NOT_READY,
                f"Task run has no output result yet: {task_run_id}",
            )

        restored_results = collect_results_from_snapshot(task_run_id, snapshot.results)
        if not restored_results:
            raise AppError(
                ErrorCode.TASK_RESULT_NOT_READY,
                f"Task run has no output result yet: {task_run_id}",
            )

        final_result = restored_results[0]
        return final_result.content, final_result.format
