from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any, Protocol
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.auth import require_workspace_capability
from app.config import get_settings
from app.repositories.test_set_repository import TestSetRepository
from app.services.document_thumbnail import (
    ThumbnailGenerationError,
    UnsupportedThumbnailMimeTypeError,
    generate_document_thumbnail,
)
from app.services.workspace_access import ResolvedContext
from app.storage.test_set_storage import TestSetStorage

router = APIRouter(prefix="/test-sets", tags=["test-documents"])
logger = logging.getLogger(__name__)


async def get_test_set_repository(request: Request) -> TestSetRepository:
    repository: TestSetRepository | None = getattr(request.app.state, "test_set_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Test set repository not initialised")
    return repository


async def get_test_set_storage(request: Request) -> TestSetStorage:
    storage: TestSetStorage | None = getattr(request.app.state, "test_set_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Test set storage not initialised")
    return storage


async def get_ground_truth_repository(request: Request) -> object | None:
    return getattr(request.app.state, "ground_truth_repository", None)


class GroundTruthRepositoryLike(Protocol):
    async def list_versions(
        self,
        document_id: str,
        *,
        workspace_id: str | None = None,
    ) -> list[Any]: ...


TestSetRepositoryDep = Annotated[TestSetRepository, Depends(get_test_set_repository)]
TestSetStorageDep = Annotated[TestSetStorage, Depends(get_test_set_storage)]
GroundTruthRepositoryDep = Annotated[
    GroundTruthRepositoryLike | None,
    Depends(get_ground_truth_repository),
]
DocumentUploadContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("document.upload")),
]
DatasetViewContextDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("dataset.view")),
]


def _document_payload(
    document: Any,
    *,
    has_ground_truth: bool,
    gt_version_count: int,
) -> dict[str, object]:
    return {
        "id": document.id,
        "test_set_id": document.test_set_id,
        "filename": document.filename,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "page_count": document.page_count,
        "has_ground_truth": has_ground_truth,
        "gt_version_count": gt_version_count,
        "created_at": document.created_at.isoformat(),
    }


async def _ground_truth_count(
    repository: GroundTruthRepositoryLike | None,
    document_id: str,
    *,
    workspace_id: str | None = None,
) -> int:
    if repository is None:
        return 0
    versions = await repository.list_versions(document_id, workspace_id=workspace_id)
    return len(versions)


async def _resolve_test_set_context(
    *,
    test_set_id: str,
    repository: TestSetRepository,
    context: ResolvedContext,
) -> Any:
    test_set = await repository.get_test_set(
        test_set_id,
        workspace_id=context.workspace_id,
    )
    if test_set is None:
        raise HTTPException(status_code=404, detail=f"Test set not found: {test_set_id}")
    return test_set


@router.post("/{test_set_id}/documents/upload", response_model=None, status_code=201)
async def upload_documents(
    test_set_id: str,
    files: Annotated[list[UploadFile], File(...)],
    repository: TestSetRepositoryDep,
    storage: TestSetStorageDep,
    context: DocumentUploadContextDep,
) -> JSONResponse:
    settings = get_settings()
    uploaded: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    for file in files:
        mime_type = (file.content_type or "").lower()
        raw_filename = (file.filename or "upload.bin").replace("\\", "/")
        filename = Path(raw_filename).name

        if mime_type not in {"application/pdf", "image/png", "image/jpeg", "image/webp"}:
            errors.append(
                {
                    "filename": filename,
                    "error": f"Unsupported file type: {mime_type or 'unknown'}",
                }
            )
            continue

        content = await file.read()
        if not content:
            errors.append({"filename": filename, "error": "Empty file"})
            continue

        max_size_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(content) > max_size_bytes:
            errors.append({"filename": filename, "error": f"File too large: {filename}"})
            continue

        doc_id = f"doc_{uuid4()}"
        storage_path = await storage.save_document(test_set_id, doc_id, filename, content)
        page_count = 1 if mime_type == "application/pdf" else None
        document = await repository.create_test_document(
            test_set_id=test_set_id,
            filename=filename,
            mime_type=mime_type,
            storage_path=storage_path,
            size_bytes=len(content),
            page_count=page_count,
            document_id=doc_id,
        )
        uploaded.append(
            {
                "id": document.id,
                "filename": document.filename,
                "mime_type": document.mime_type,
                "size_bytes": document.size_bytes,
            }
        )

    return JSONResponse(status_code=201, content={"uploaded": uploaded, "errors": errors})


@router.get("/{test_set_id}/documents", response_model=None)
async def list_documents(
    test_set_id: str,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    documents = await repository.list_test_documents(
        test_set_id,
        workspace_id=context.workspace_id,
    )
    items = []
    for document in documents:
        gt_count = await _ground_truth_count(
            ground_truth_repository,
            document.id,
            workspace_id=context.workspace_id,
        )
        items.append(
            _document_payload(
                document,
                has_ground_truth=gt_count > 0,
                gt_version_count=gt_count,
            )
        )
    return {"items": items, "total": len(items)}


@router.get("/{test_set_id}/documents/{document_id}", response_model=None)
async def get_document(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    ground_truth_repository: GroundTruthRepositoryDep,
    context: DatasetViewContextDep,
) -> dict[str, object]:
    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    document = await repository.get_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )
    if document is None or document.test_set_id != test_set_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    gt_count = await _ground_truth_count(
        ground_truth_repository,
        document.id,
        workspace_id=context.workspace_id,
    )
    return _document_payload(document, has_ground_truth=gt_count > 0, gt_version_count=gt_count)


@router.get("/{test_set_id}/documents/{document_id}/file", response_model=None)
async def get_document_file(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    storage: TestSetStorageDep,
    context: DatasetViewContextDep,
    disposition: str = "attachment",
) -> Response:
    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    document = await repository.get_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )
    if document is None or document.test_set_id != test_set_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    content = await storage.read_document(document.storage_path)

    if disposition == "inline":
        content_disposition = "inline"
    else:
        content_disposition = f'attachment; filename="{document.filename}"'

    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": content_disposition},
    )


@router.get("/{test_set_id}/documents/{document_id}/thumbnail", response_model=None)
async def get_document_thumbnail(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    storage: TestSetStorageDep,
    context: DatasetViewContextDep,
    size: int = 96,
) -> Response:
    if size not in {96, 640}:
        raise HTTPException(status_code=422, detail="Thumbnail size must be 96 or 640")

    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    document = await repository.get_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )
    if document is None or document.test_set_id != test_set_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    thumbnail = await storage.read_thumbnail(test_set_id, document_id, size)
    if thumbnail is None:
        content = await storage.read_document(document.storage_path)
        loop = asyncio.get_running_loop()
        try:
            thumbnail = await loop.run_in_executor(
                None,
                generate_document_thumbnail,
                content,
                document.mime_type,
                size,
            )
        except UnsupportedThumbnailMimeTypeError as exc:
            raise HTTPException(
                status_code=415,
                detail="Thumbnail not supported for this file type",
            ) from exc
        except ThumbnailGenerationError as exc:
            logger.warning("Failed to generate thumbnail for document %s", document_id)
            raise HTTPException(
                status_code=422,
                detail="Document thumbnail could not be generated",
            ) from exc
        await storage.save_thumbnail(test_set_id, document_id, size, thumbnail)

    return Response(
        content=thumbnail,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=86400, immutable",
            "Vary": "Cookie",
        },
    )


@router.delete("/{test_set_id}/documents/{document_id}", status_code=204)
async def delete_document(
    test_set_id: str,
    document_id: str,
    repository: TestSetRepositoryDep,
    storage: TestSetStorageDep,
    context: DocumentUploadContextDep,
) -> Response:
    await _resolve_test_set_context(
        test_set_id=test_set_id,
        repository=repository,
        context=context,
    )

    document = await repository.get_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )
    if document is None or document.test_set_id != test_set_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    await repository.delete_test_document(
        document_id,
        workspace_id=context.workspace_id,
    )

    try:
        await storage.delete_document(document.storage_path)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to clean up storage for deleted document %s error_type=%s",
            document_id,
            type(exc).__name__,
        )
    try:
        await storage.delete_document_thumbnails(test_set_id, document_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to clean up thumbnails for deleted document %s error_type=%s",
            document_id,
            type(exc).__name__,
        )
    return Response(status_code=204)
