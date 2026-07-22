from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.auth import require_workspace_capability
from app.models.db.test_document import TestDocument
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.workspace_access import ResolvedContext

router = APIRouter(prefix="/test-sets", tags=["ground-truths"])


async def get_test_set_repository(request: Request) -> TestSetRepository:
    repository: TestSetRepository | None = getattr(request.app.state, "test_set_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Test set repository not initialised")
    return repository


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


async def get_evaluation_service(request: Request) -> object:
    service = getattr(request.app.state, "evaluation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Evaluation service not initialised")
    return service


class EvaluationServiceLike(Protocol):
    async def apply_result_as_ground_truth(
        self,
        *,
        document_id: str,
        task_run_id: str,
        notes: str | None,
        workspace_id: str,
        requested_by_user_id: str,
    ) -> Any: ...


TestSetRepositoryDep = Annotated[TestSetRepository, Depends(get_test_set_repository)]
GroundTruthRepositoryDep = Annotated[
    GroundTruthRepository,
    Depends(get_ground_truth_repository),
]
EvaluationServiceDep = Annotated[
    EvaluationServiceLike,
    Depends(get_evaluation_service),
]
GroundTruthManageContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("ground_truth.manage")),
]
DatasetViewContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("dataset.view")),
]


class GroundTruthCreateRequest(BaseModel):
    content: str
    format: str = "text"
    source: str
    notes: str | None = None


class GroundTruthApplyRequest(BaseModel):
    task_run_id: str
    notes: str | None = None


def _serialize_ground_truth(record: Any) -> dict[str, object]:
    payload = {
        "id": record.id,
        "document_id": record.document_id,
        "version": record.version,
        "source": record.source,
        "format": record.format,
        "content": record.content,
        "notes": record.notes,
        "created_at": record.created_at.isoformat(),
    }
    source_task_run_id = getattr(record, "source_task_run_id", None)
    if source_task_run_id is not None:
        payload["source_task_run_id"] = source_task_run_id
    return payload


def _active_workspace_id(context: ResolvedContext) -> str:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return context.workspace_id


async def _require_document(
    *,
    test_set_id: str,
    document_id: str,
    repository: TestSetRepository,
    context: ResolvedContext,
) -> TestDocument:
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
    return document


@router.post(
    "/{test_set_id}/documents/{document_id}/ground-truth",
    response_model=None,
    status_code=201,
)
async def create_ground_truth(
    test_set_id: str,
    document_id: str,
    payload: GroundTruthCreateRequest,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: GroundTruthManageContextDep,
) -> dict[str, object]:
    await _require_document(
        test_set_id=test_set_id,
        document_id=document_id,
        repository=repository,
        context=context,
    )
    record = await ground_truth_repository.create_version(
        document_id=document_id,
        source=payload.source,
        format=payload.format,
        content=payload.content,
        notes=payload.notes,
        workspace_id=context.workspace_id,
    )
    return _serialize_ground_truth(record)


@router.get("/{test_set_id}/documents/{document_id}/ground-truth", response_model=None)
async def get_latest_ground_truth(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    await _require_document(
        test_set_id=test_set_id,
        document_id=document_id,
        repository=repository,
        context=context,
    )
    record = await ground_truth_repository.get_latest(
        document_id,
        workspace_id=context.workspace_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No ground truth found for document {document_id}",
        )
    return _serialize_ground_truth(record)


@router.get("/{test_set_id}/documents/{document_id}/ground-truth/versions", response_model=None)
async def list_ground_truth_versions(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    await _require_document(
        test_set_id=test_set_id,
        document_id=document_id,
        repository=repository,
        context=context,
    )
    records = await ground_truth_repository.list_versions(
        document_id,
        workspace_id=context.workspace_id,
    )
    items = []
    for record in records:
        item = {
            "id": record.id,
            "version": record.version,
            "source": record.source,
            "format": record.format,
            "notes": record.notes,
            "created_at": record.created_at.isoformat(),
        }
        source_task_run_id = getattr(record, "source_task_run_id", None)
        if source_task_run_id is not None:
            item["source_task_run_id"] = source_task_run_id
        items.append(item)
    return {"items": items, "total": len(items)}


@router.get(
    "/{test_set_id}/documents/{document_id}/ground-truth/versions/{version}",
    response_model=None,
)
async def get_ground_truth_version(
    test_set_id: str,
    document_id: str,
    version: int,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    await _require_document(
        test_set_id=test_set_id,
        document_id=document_id,
        repository=repository,
        context=context,
    )
    record = await ground_truth_repository.get_version(
        document_id,
        version,
        workspace_id=context.workspace_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(f"Ground truth version {version} not found for document {document_id}"),
        )
    return _serialize_ground_truth(record)


@router.post(
    "/{test_set_id}/documents/{document_id}/ground-truth/apply",
    response_model=None,
    status_code=201,
)
async def apply_ground_truth(
    test_set_id: str,
    document_id: str,
    payload: GroundTruthApplyRequest,
    repository: TestSetRepositoryDep,
    evaluation_service: EvaluationServiceDep,
    context: GroundTruthManageContextDep,
) -> dict[str, object]:
    await _require_document(
        test_set_id=test_set_id,
        document_id=document_id,
        repository=repository,
        context=context,
    )
    record = await evaluation_service.apply_result_as_ground_truth(
        document_id=document_id,
        task_run_id=payload.task_run_id,
        notes=payload.notes,
        workspace_id=_active_workspace_id(context),
        requested_by_user_id=context.user.id,
    )
    return _serialize_ground_truth(record)
