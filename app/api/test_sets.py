from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.auth import require_workspace_capability
from app.repositories.test_set_repository import TestSetRepository
from app.services.workspace_access import ResolvedContext
from app.storage.test_set_storage import TestSetStorage

router = APIRouter(prefix="/test-sets", tags=["test-sets"])
logger = logging.getLogger(__name__)


async def get_test_set_repository(request: Request) -> TestSetRepository:
    repository: TestSetRepository | None = getattr(request.app.state, "test_set_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Test set repository not initialised")
    return repository


TestSetRepositoryDep = Annotated[TestSetRepository, Depends(get_test_set_repository)]


async def get_test_set_storage(request: Request) -> TestSetStorage:
    storage: TestSetStorage | None = getattr(request.app.state, "test_set_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Test set storage not initialised")
    return storage


TestSetStorageDep = Annotated[TestSetStorage, Depends(get_test_set_storage)]
DatasetCreateContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("dataset.create")),
]
DatasetViewContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("dataset.view")),
]


class TestSetCreateRequest(BaseModel):
    name: str
    description: str | None = None


class TestSetUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


def _serialize_test_set(record: Any) -> dict[str, object]:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "workspace_id": record.workspace_id,
        "document_count": record.document_count,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.post("", response_model=None, status_code=201)
async def create_test_set(
    payload: TestSetCreateRequest,
    repository: TestSetRepositoryDep,
    context: DatasetCreateContextDep,
) -> dict[str, object]:
    record = await repository.create_test_set(
        name=payload.name,
        description=payload.description,
        workspace_id=context.workspace_id,
    )
    return _serialize_test_set(record)


@router.get("", response_model=None)
async def list_test_sets(
    repository: TestSetRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    items = await repository.list_test_sets(workspace_id=context.workspace_id)
    return {
        "items": [_serialize_test_set(item) for item in items],
        "total": len(items),
    }


@router.get("/{test_set_id}", response_model=None)
async def get_test_set(
    test_set_id: str,
    repository: TestSetRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    record = await repository.get_test_set(test_set_id, workspace_id=context.workspace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")
    return _serialize_test_set(record)


@router.patch("/{test_set_id}", response_model=None)
async def update_test_set(
    test_set_id: str,
    payload: TestSetUpdateRequest,
    repository: TestSetRepositoryDep,
    context: DatasetCreateContextDep,
) -> dict[str, object]:
    if payload.name is not None and payload.name.strip() == "":
        raise HTTPException(status_code=422, detail="Name must not be empty")

    updates: dict[str, object] = {}
    if "name" in payload.model_fields_set:
        updates["name"] = payload.name
    if "description" in payload.model_fields_set:
        updates["description"] = payload.description

    record = await repository.update_test_set(
        test_set_id,
        updates=updates,
        workspace_id=context.workspace_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")
    return _serialize_test_set(record)


@router.delete("/{test_set_id}", status_code=204)
async def delete_test_set(
    test_set_id: str,
    repository: TestSetRepositoryDep,
    storage: TestSetStorageDep,
    context: DatasetCreateContextDep,
) -> Response:
    try:
        await repository.delete_test_set(test_set_id, workspace_id=context.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}") from exc

    try:
        await storage.delete_test_set(test_set_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to clean up storage for deleted test set %s error_type=%s",
            test_set_id,
            type(exc).__name__,
        )
    return Response(status_code=204)
