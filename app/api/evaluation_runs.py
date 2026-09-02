from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Annotated, Any, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import require_workspace_capability
from app.api.workflows import get_workflow_store
from app.core.feature_flags import FeatureFlags
from app.models.workflow import WorkflowDefinition
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.workspace_access import ResolvedContext

router = APIRouter(tags=["evaluation-runs"])

logger = logging.getLogger(__name__)
_evaluation_run_locks: dict[str, asyncio.Lock] = {}


class EvaluationServiceLike(Protocol):
    async def run_batch(
        self,
        *,
        run_id: str,
        test_set_id: str,
        workflow: WorkflowDefinition,
        workspace_id: str | None = None,
    ) -> None: ...

    async def cancel_run(
        self,
        run_id: str,
        *,
        workspace_id: str,
    ) -> Any | None: ...


class WorkflowStoreLike(Protocol):
    def get(self, workflow_id: str, *, workspace_id: str | None = None) -> Any: ...


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _schedule_background_run(coro: Coroutine[Any, Any, object]) -> asyncio.Task[object]:
    return asyncio.create_task(coro)


def _get_evaluation_run_lock(test_set_id: str) -> asyncio.Lock:
    return _evaluation_run_locks.setdefault(test_set_id, asyncio.Lock())


def _register_background_task(request: Request, task: object) -> None:
    if not isinstance(task, asyncio.Task):
        return

    background_tasks: set[asyncio.Task[object]] | None = getattr(
        request.app.state,
        "evaluation_background_tasks",
        None,
    )
    if background_tasks is None:
        background_tasks = set()
        request.app.state.evaluation_background_tasks = background_tasks

    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _run_batch_with_failure_guard(
    *,
    evaluation_service: EvaluationServiceLike,
    evaluation_repository: EvaluationRepository,
    run_id: str,
    test_set_id: str,
    workflow: WorkflowDefinition,
    workspace_id: str | None,
) -> None:
    try:
        await evaluation_service.run_batch(
            run_id=run_id,
            test_set_id=test_set_id,
            workflow=workflow,
            workspace_id=workspace_id,
        )
    except asyncio.CancelledError:
        logger.warning("Evaluation run %s cancelled during background execution", run_id)
        run = await evaluation_repository.get_run(run_id, workspace_id=workspace_id)
        if run is not None:
            await evaluation_repository.update_run(
                run_id,
                status="failed",
                completed_count=run.completed_count,
                failed_count=run.failed_count,
                duration_ms=run.duration_ms,
                started_at=run.started_at or run.created_at,
                completed_at=_utcnow_naive(),
                workspace_id=workspace_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Evaluation run %s failed in background execution error_type=%s",
            run_id,
            type(exc).__name__,
        )
        run = await evaluation_repository.get_run(run_id, workspace_id=workspace_id)
        if run is not None:
            await evaluation_repository.update_run(
                run_id,
                status="failed",
                completed_count=run.completed_count,
                failed_count=run.failed_count,
                duration_ms=run.duration_ms,
                started_at=run.started_at or run.created_at,
                completed_at=_utcnow_naive(),
                workspace_id=workspace_id,
            )


async def get_test_set_repository(request: Request) -> TestSetRepository:
    repository: TestSetRepository | None = getattr(request.app.state, "test_set_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Test set repository not initialised")
    return repository


async def get_evaluation_repository(request: Request) -> EvaluationRepository:
    repository: EvaluationRepository | None = getattr(
        request.app.state,
        "evaluation_repository",
        None,
    )
    if repository is None:
        repository = EvaluationRepository()
        request.app.state.evaluation_repository = repository
    return repository


async def get_evaluation_service(request: Request) -> EvaluationServiceLike:
    service = cast(
        EvaluationServiceLike | None,
        getattr(request.app.state, "evaluation_service", None),
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Evaluation service not initialised")
    return service


def _get_workflow_store(request: Request) -> WorkflowStoreLike:
    workflow_store = getattr(request.app.state, "workflow_store", None)
    return cast(WorkflowStoreLike, workflow_store or get_workflow_store())


TestSetRepositoryDep = Annotated[TestSetRepository, Depends(get_test_set_repository)]
EvaluationRepositoryDep = Annotated[EvaluationRepository, Depends(get_evaluation_repository)]
EvaluationServiceDep = Annotated[EvaluationServiceLike, Depends(get_evaluation_service)]


async def get_ground_truth_repository(request: Request) -> GroundTruthRepository:
    repository: GroundTruthRepository | None = getattr(
        request.app.state,
        "ground_truth_repository",
        None,
    )
    if repository is None:
        repository = GroundTruthRepository()
        request.app.state.ground_truth_repository = repository
    return repository


GroundTruthRepositoryDep = Annotated[GroundTruthRepository, Depends(get_ground_truth_repository)]
WorkflowRunContextDep = Annotated[
    ResolvedContext, Depends(require_workspace_capability("workflow.run"))
]
RunViewContextDep = Annotated[ResolvedContext, Depends(require_workspace_capability("run.view"))]
RunCancelContextDep = Annotated[
    ResolvedContext, Depends(require_workspace_capability("run.cancel"))
]
ComparisonRefreshContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("comparison.refresh")),
]
GroundTruthManageContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("ground_truth.manage")),
]


class EvaluationRunCreateRequest(BaseModel):
    workflow_id: str
    name: str | None = None
    document_ids: list[str] | None = None
    client_request_id: str | None = None


def _serialize_run(record: Any) -> dict[str, object]:
    return {
        "id": record.id,
        "name": record.name,
        "test_set_id": record.test_set_id,
        "workflow_id": record.workflow_id,
        "workflow_version": record.workflow_version,
        "client_request_id": record.client_request_id,
        "status": record.status,
        "total_documents": record.total_documents,
        "completed_count": record.completed_count,
        "failed_count": record.failed_count,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "duration_ms": record.duration_ms,
        "created_at": record.created_at.isoformat(),
    }


def _ensure_same_workspace(
    *, test_set_workspace_id: str | None, workflow_workspace_id: str | None
) -> None:
    if test_set_workspace_id is None or workflow_workspace_id is None:
        logger.warning(
            "Evaluation run workspace check allowed null workspace: "
            "test_set_workspace_id=%s workflow_workspace_id=%s",
            test_set_workspace_id,
            workflow_workspace_id,
        )
        return
    if test_set_workspace_id != workflow_workspace_id:
        raise HTTPException(status_code=409, detail="WORKFLOW_DATASET_DIFFERENT_WORKSPACE")


@router.post("/test-sets/{test_set_id}/evaluation-runs", response_model=None, status_code=201)
async def create_evaluation_run(
    test_set_id: str,
    payload: EvaluationRunCreateRequest,
    request: Request,
    context: WorkflowRunContextDep,
    repository: TestSetRepositoryDep,
    evaluation_repository: EvaluationRepositoryDep,
    evaluation_service: EvaluationServiceDep,
) -> dict[str, object] | JSONResponse:
    test_set = await repository.get_test_set(test_set_id, workspace_id=context.workspace_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")

    workflow_store = _get_workflow_store(request)
    workflow = workflow_store.get(payload.workflow_id, workspace_id=context.workspace_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {payload.workflow_id}")
    _ensure_same_workspace(
        test_set_workspace_id=test_set.workspace_id,
        workflow_workspace_id=workflow.workspace_id,
    )

    # Idempotency: check before lock for quick early return
    if payload.client_request_id:
        existing = await evaluation_repository.find_run_by_client_request_id(
            test_set_id, payload.client_request_id, workspace_id=context.workspace_id
        )
        if existing is not None:
            return JSONResponse(status_code=200, content=_serialize_run(existing))

    queue_mode = FeatureFlags.is_queue_mode()

    async with _get_evaluation_run_lock(test_set_id):
        # Re-check idempotency inside lock to handle race conditions
        if payload.client_request_id:
            existing = await evaluation_repository.find_run_by_client_request_id(
                test_set_id, payload.client_request_id, workspace_id=context.workspace_id
            )
            if existing is not None:
                return JSONResponse(status_code=200, content=_serialize_run(existing))

        active_run = await evaluation_repository.get_active_run_for_test_set(
            test_set_id,
            workspace_id=context.workspace_id,
        )
        if active_run is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Evaluation run already active for test set {test_set_id}: {active_run.id}",
            )

        all_documents = await repository.list_test_documents(
            test_set_id,
            workspace_id=context.workspace_id,
        )
        if payload.document_ids is not None and len(payload.document_ids) > 0:
            all_doc_ids = {doc.id for doc in all_documents}
            invalid_ids = [doc_id for doc_id in payload.document_ids if doc_id not in all_doc_ids]
            if invalid_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid document IDs for test set {test_set_id}: {invalid_ids}",
                )
            selected_doc_ids = payload.document_ids
        else:
            selected_doc_ids = [doc.id for doc in all_documents]

        run, _results = await evaluation_repository.create_run_with_results(
            test_set_id=test_set_id,
            workflow_id=workflow.id,
            workflow_version=workflow.published_version or workflow.latest_version,
            workflow_snapshot_json=workflow.definition.model_dump(mode="json"),
            name=payload.name,
            total_documents=len(selected_doc_ids),
            client_request_id=payload.client_request_id,
            document_ids=selected_doc_ids,
            workspace_id=test_set.workspace_id,
            queue_mode=queue_mode,
        )

    if not queue_mode:
        background_task = _schedule_background_run(
            _run_batch_with_failure_guard(
                evaluation_service=evaluation_service,
                evaluation_repository=evaluation_repository,
                run_id=run.id,
                test_set_id=test_set_id,
                workflow=workflow.definition,
                workspace_id=run.workspace_id,
            )
        )
        _register_background_task(request, background_task)
    return _serialize_run(run)


@router.get("/test-sets/{test_set_id}/evaluation-runs", response_model=None)
async def list_evaluation_runs(
    test_set_id: str,
    request: Request,
    context: RunViewContextDep,
    repository: TestSetRepositoryDep,
    evaluation_repository: EvaluationRepositoryDep,
) -> dict[str, object]:
    test_set = await repository.get_test_set(test_set_id, workspace_id=context.workspace_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")

    runs = await evaluation_repository.list_runs_for_test_set(
        test_set_id,
        workspace_id=context.workspace_id,
    )
    workflow_store = _get_workflow_store(request)

    items = []
    for run in runs:
        result_summary_raw = await evaluation_repository.get_result_summary_for_run(
            run.id,
            workspace_id=context.workspace_id,
        )
        review_summary_raw = await evaluation_repository.get_review_summary_for_run(
            run.id,
            workspace_id=context.workspace_id,
        )
        comparison_summary_raw = await evaluation_repository.get_comparison_summary_for_run(
            run.id,
            workspace_id=context.workspace_id,
        )

        workflow = (
            workflow_store.get(run.workflow_id, workspace_id=context.workspace_id)
            if run.workflow_id
            else None
        )
        workflow_name = workflow.name if workflow is not None else None

        items.append(
            {
                **_serialize_run(run),
                "workflow_name": workflow_name,
                "result_summary": {
                    "total": sum(result_summary_raw.values()),
                    "completed": result_summary_raw.get("completed", 0),
                    "failed": result_summary_raw.get("failed", 0),
                    "queued": result_summary_raw.get("queued", 0),
                    "running": result_summary_raw.get("running", 0),
                    "skipped": result_summary_raw.get("skipped", 0),
                },
                "review_summary": {
                    "accepted": review_summary_raw.get("accepted", 0),
                    "rejected": review_summary_raw.get("rejected", 0),
                    "unreviewed": review_summary_raw.get("unreviewed", 0),
                },
                "comparison_summary": {
                    "matched": comparison_summary_raw.get("matched", 0),
                    "mismatched": comparison_summary_raw.get("mismatched", 0),
                    "not_compared": comparison_summary_raw.get("not_compared", 0),
                    "unavailable": comparison_summary_raw.get("unavailable", 0),
                },
            }
        )

    return {"items": items, "total": len(items)}


@router.get(
    "/test-sets/{test_set_id}/documents/{document_id}/evaluation-runs",
    response_model=None,
)
async def list_document_evaluation_runs(
    test_set_id: str,
    document_id: str,
    request: Request,
    context: RunViewContextDep,
    repository: TestSetRepositoryDep,
    evaluation_repository: EvaluationRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    test_set = await repository.get_test_set(
        test_set_id,
        workspace_id=context.workspace_id,
    )
    if test_set is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")

    document = await repository.get_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )
    if document is None or document.test_set_id != test_set_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    rows, total = await evaluation_repository.list_document_run_history(
        test_set_id=test_set_id,
        document_id=document_id,
        limit=limit,
        offset=offset,
        workspace_id=context.workspace_id,
    )
    workflow_store = _get_workflow_store(request)
    items: list[dict[str, object]] = []
    for result, run in rows:
        workflow = (
            workflow_store.get(run.workflow_id, workspace_id=context.workspace_id)
            if run.workflow_id
            else None
        )
        items.append(
            {
                "run_id": run.id,
                "result_id": result.id,
                "run_name": run.name,
                "workflow_id": run.workflow_id,
                "workflow_name": workflow.name if workflow is not None else None,
                "run_status": run.status,
                "result_status": result.status,
                "processing_time_ms": result.processing_time_ms,
                "error": result.error,
                "comparison_status": result.comparison_status,
                "review_status": result.review_status,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "run_duration_ms": run.duration_ms,
            }
        )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/evaluation-runs/{run_id}", response_model=None)
async def get_evaluation_run(
    run_id: str,
    context: RunViewContextDep,
    evaluation_repository: EvaluationRepositoryDep,
) -> dict[str, object]:
    run = await evaluation_repository.get_run(run_id, workspace_id=context.workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
    return _serialize_run(run)


@router.post("/evaluation-runs/{run_id}/cancel", response_model=None)
async def cancel_evaluation_run(
    run_id: str,
    context: RunCancelContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    evaluation_service: EvaluationServiceDep,
) -> dict[str, object]:
    if context.workspace_id is None:
        raise HTTPException(status_code=400, detail="Workspace scope required")
    cancellation = await evaluation_service.cancel_run(
        run_id,
        workspace_id=context.workspace_id,
    )
    if cancellation is None:
        run = await evaluation_repository.get_run(run_id, workspace_id=context.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
        raise HTTPException(
            status_code=409,
            detail=f"Evaluation run {run_id} is already terminal ({run.status})",
        )

    return {
        **_serialize_run(cancellation.run),
        "already_cancelled": cancellation.already_cancelled,
        "revoked_task_count": len(cancellation.published_task_ids),
    }


@router.get("/evaluation-runs/{run_id}/results", response_model=None)
async def list_evaluation_results(
    run_id: str,
    context: RunViewContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    test_set_repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
) -> dict[str, object]:
    run = await evaluation_repository.get_run(run_id, workspace_id=context.workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
    results = await evaluation_repository.list_results(run_id, workspace_id=context.workspace_id)
    documents = {
        doc.id: doc
        for doc in await test_set_repository.list_test_documents(
            run.test_set_id,
            workspace_id=context.workspace_id,
        )
    }
    document_ids_with_ground_truth = (
        await ground_truth_repository.get_document_ids_with_ground_truth(
            [result.document_id for result in results],
            workspace_id=context.workspace_id,
        )
    )
    payload = []
    for result in results:
        document = documents.get(result.document_id)
        payload.append(
            {
                "id": result.id,
                "document_id": result.document_id,
                "filename": document.filename if document is not None else None,
                "status": result.status,
                "processing_time_ms": result.processing_time_ms,
                "output_format": result.output_format,
                "error": result.error,
                "comparison_status": result.comparison_status,
                "review_status": result.review_status,
                "has_ground_truth": result.document_id in document_ids_with_ground_truth,
            }
        )
    return {
        "evaluation_run_id": run_id,
        "status": run.status,
        "summary": {
            "total": len(results),
            "completed": sum(1 for item in results if item.status == "completed"),
            "failed": sum(1 for item in results if item.status == "failed"),
            "queued": sum(1 for item in results if item.status == "queued"),
            "running": sum(1 for item in results if item.status == "running"),
            "skipped": sum(1 for item in results if item.status == "skipped"),
        },
        "results": payload,
    }


@router.get("/evaluation-runs/{run_id}/results/{result_id}", response_model=None)
async def get_evaluation_result_detail(
    run_id: str,
    result_id: str,
    context: RunViewContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    test_set_repository: TestSetRepositoryDep,
) -> dict[str, object]:
    run = await evaluation_repository.get_run(run_id, workspace_id=context.workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
    results = await evaluation_repository.list_results(run_id, workspace_id=context.workspace_id)
    result = next((item for item in results if item.id == result_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Evaluation result not found: {result_id}")
    document = await test_set_repository.get_test_document(
        result.document_id,
        workspace_id=context.workspace_id,
    )
    return {
        "id": result.id,
        "evaluation_run_id": result.evaluation_run_id,
        "document_id": result.document_id,
        "filename": document.filename if document is not None else None,
        "task_run_id": result.task_run_id,
        "status": result.status,
        "output_content": result.output_content,
        "output_format": result.output_format,
        "processing_time_ms": result.processing_time_ms,
        "created_at": result.created_at.isoformat(),
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Result-Scoped Review (Accept / Reject)
# ---------------------------------------------------------------------------


class AcceptReviewRequest(BaseModel):
    notes: str | None = None


class RejectReviewRequest(BaseModel):
    reason: str | None = None


def _serialize_review_result(
    result: Any,
    *,
    has_ground_truth: bool,
) -> dict[str, object]:
    return {
        "id": result.id,
        "evaluation_run_id": result.evaluation_run_id,
        "document_id": result.document_id,
        "status": result.status,
        "review_status": result.review_status,
        "accepted_ground_truth_id": result.accepted_ground_truth_id,
        "reviewed_at": result.reviewed_at.isoformat() if result.reviewed_at else None,
        "review_notes": result.review_notes,
        "comparison_status": result.comparison_status,
        "has_ground_truth": has_ground_truth,
    }


async def _get_validated_result(
    run_id: str,
    result_id: str,
    evaluation_repository: EvaluationRepository,
    workspace_id: str | None,
) -> Any:
    run = await evaluation_repository.get_run(run_id, workspace_id=workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
    result = await evaluation_repository.get_result(result_id, workspace_id=workspace_id)
    if result is None or result.evaluation_run_id != run_id:
        raise HTTPException(status_code=404, detail=f"Evaluation result not found: {result_id}")
    if result.status != "completed":
        raise HTTPException(
            status_code=422,
            detail="Only completed results can be reviewed",
        )
    return result


# ---------------------------------------------------------------------------
# Compare Endpoint
# ---------------------------------------------------------------------------


def _normalize_text(text: str | None) -> str:
    """Normalize text for comparison: strip, collapse whitespace."""
    if text is None:
        return ""
    return " ".join(text.split())


async def _build_comparison(
    run_id: str,
    result_id: str,
    *,
    workspace_id: str | None,
    evaluation_repository: EvaluationRepository,
    ground_truth_repository: GroundTruthRepository,
    persist: bool,
) -> dict[str, object]:
    run = await evaluation_repository.get_run(run_id, workspace_id=workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run not found: {run_id}")
    result = await evaluation_repository.get_result(result_id, workspace_id=workspace_id)
    if result is None or result.evaluation_run_id != run_id:
        raise HTTPException(status_code=404, detail=f"Evaluation result not found: {result_id}")

    # Non-completed results cannot be compared
    if result.status != "completed":
        return {
            "result_id": result.id,
            "document_id": result.document_id,
            "comparison_status": "not_compared",
            "diff_mode": "none",
            "expected_content": None,
            "actual_content": None,
            "diff_fields": [],
        }

    gt = await ground_truth_repository.get_latest(
        result.document_id,
        workspace_id=workspace_id,
    )
    if gt is None:
        if persist:
            await evaluation_repository.update_result_comparison_status(
                result.id,
                comparison_status="unavailable",
                workspace_id=workspace_id,
            )
        return {
            "result_id": result.id,
            "document_id": result.document_id,
            "comparison_status": "unavailable",
            "diff_mode": "none",
            "expected_content": None,
            "actual_content": result.output_content,
            "diff_fields": [],
        }

    expected_normalized = _normalize_text(gt.content)
    actual_normalized = _normalize_text(result.output_content)
    comparison_status = "matched" if expected_normalized == actual_normalized else "mismatched"

    if persist:
        await evaluation_repository.update_result_comparison_status(
            result.id,
            comparison_status=comparison_status,
            workspace_id=workspace_id,
        )

    return {
        "result_id": result.id,
        "document_id": result.document_id,
        "comparison_status": comparison_status,
        "diff_mode": "text",
        "expected_content": gt.content,
        "actual_content": result.output_content,
        "diff_fields": [],
    }


@router.get(
    "/evaluation-runs/{run_id}/results/{result_id}/comparison",
    response_model=None,
)
async def get_result_comparison(
    run_id: str,
    result_id: str,
    context: RunViewContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
) -> dict[str, object]:
    """Calculate and return a comparison without mutating persisted result state."""
    return await _build_comparison(
        run_id,
        result_id,
        workspace_id=context.workspace_id,
        evaluation_repository=evaluation_repository,
        ground_truth_repository=ground_truth_repository,
        persist=False,
    )


@router.post(
    "/evaluation-runs/{run_id}/results/{result_id}/comparison",
    response_model=None,
)
async def refresh_result_comparison(
    run_id: str,
    result_id: str,
    context: ComparisonRefreshContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
) -> dict[str, object]:
    """Recalculate a comparison and persist its derived status."""
    return await _build_comparison(
        run_id,
        result_id,
        workspace_id=context.workspace_id,
        evaluation_repository=evaluation_repository,
        ground_truth_repository=ground_truth_repository,
        persist=True,
    )


@router.get(
    "/evaluation-runs/{run_id}/results/{result_id}/compare",
    response_model=None,
    deprecated=True,
)
async def compare_result_compatibility(
    run_id: str,
    result_id: str,
    context: RunViewContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
) -> dict[str, object]:
    """Deprecated read-only alias for the canonical comparison GET."""
    return await _build_comparison(
        run_id,
        result_id,
        workspace_id=context.workspace_id,
        evaluation_repository=evaluation_repository,
        ground_truth_repository=ground_truth_repository,
        persist=False,
    )


@router.post(
    "/evaluation-runs/{run_id}/results/{result_id}/accept-as-ground-truth",
    response_model=None,
)
async def accept_result_as_ground_truth(
    run_id: str,
    result_id: str,
    context: GroundTruthManageContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    payload: AcceptReviewRequest | None = None,
) -> dict[str, object]:
    result = await _get_validated_result(
        run_id,
        result_id,
        evaluation_repository,
        context.workspace_id,
    )

    notes = payload.notes if payload else None

    gt = await ground_truth_repository.create_version(
        document_id=result.document_id,
        source="review_accept",
        format=result.output_format or "text",
        content=result.output_content or "",
        source_task_run_id=result.task_run_id,
        notes=notes,
        workspace_id=context.workspace_id,
    )

    updated = await evaluation_repository.update_result_review(
        result.id,
        review_status="accepted",
        accepted_ground_truth_id=gt.id,
        reviewed_at=_utcnow_naive(),
        review_notes=notes,
        comparison_status="matched",
        workspace_id=context.workspace_id,
    )
    return _serialize_review_result(updated, has_ground_truth=True)


@router.post(
    "/evaluation-runs/{run_id}/results/{result_id}/reject",
    response_model=None,
)
async def reject_result(
    run_id: str,
    result_id: str,
    context: GroundTruthManageContextDep,
    evaluation_repository: EvaluationRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    payload: RejectReviewRequest | None = None,
) -> dict[str, object]:
    result = await _get_validated_result(
        run_id,
        result_id,
        evaluation_repository,
        context.workspace_id,
    )

    reason = payload.reason if payload else None

    updated = await evaluation_repository.update_result_review(
        result.id,
        review_status="rejected",
        accepted_ground_truth_id=None,
        reviewed_at=_utcnow_naive(),
        review_notes=reason,
        workspace_id=context.workspace_id,
    )
    existing_ground_truth = await ground_truth_repository.get_latest(
        result.document_id,
        workspace_id=context.workspace_id,
    )
    return _serialize_review_result(
        updated,
        has_ground_truth=existing_ground_truth is not None,
    )
