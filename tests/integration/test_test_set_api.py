from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import get_authenticated_context
from app.api.test_documents import (
    DatasetViewContextDep as DocumentViewContextDep,
)
from app.api.test_documents import (
    DocumentUploadContextDep,
)
from app.api.test_documents import (
    router as test_documents_router,
)
from app.api.test_sets import (
    DatasetCreateContextDep,
    DatasetViewContextDep,
)
from app.api.test_sets import (
    router as test_sets_router,
)
from app.db.base import Base
from app.errors import register_exception_handlers
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.storage_cleanup_job import StorageCleanupJob
from app.repositories.test_set_repository import TestSetRepository
from app.services.document_thumbnail import UnsupportedThumbnailMimeTypeError
from app.services.storage_cleanup import retry_pending_storage_cleanups
from app.services.workspace_access import ResolvedContext
from app.storage.test_set_storage import TestSetStorage


def _image_bytes(image_format: str, size: tuple[int, int] = (800, 400)) -> bytes:
    image = Image.new("RGB", size, "navy")
    output = BytesIO()
    image.save(output, format=image_format)
    image.close()
    return output.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")
    app.dependency_overrides[get_authenticated_context] = lambda: AuthenticatedContext(
        user=AuthUser(id="usr_test_set_api", email="test-set-api@example.com"),
        session=AuthSessionInfo(
            id="as_test_set_api",
            user_id="usr_test_set_api",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
    )
    context = ResolvedContext(
        user=AuthUser(id="usr_test_set_api", email="test-set-api@example.com"),
        session=AuthSessionInfo(
            id="as_test_set_api",
            user_id="usr_test_set_api",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
        workspace_id="ws_test_set_api",
        role=None,
        capabilities=frozenset(),
    )
    for context_dependency in (
        DatasetCreateContextDep,
        DatasetViewContextDep,
        DocumentUploadContextDep,
        DocumentViewContextDep,
    ):
        dependency = get_args(context_dependency)[1].dependency
        app.dependency_overrides[dependency] = lambda: context

    db_path = tmp_path / "test_set_api.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    session_factory = asyncio.run(_prepare())
    app.state.test_set_repository = TestSetRepository(session_factory=session_factory)
    app.state.test_set_storage = TestSetStorage(tmp_path / "storage")
    app.state._test_engine = engine
    client = TestClient(app)
    try:
        yield client
    finally:
        asyncio.run(engine.dispose())


def test_create_and_list_test_sets(client: TestClient) -> None:
    created = client.post(
        "/api/test-sets",
        json={"name": "Invoices", "description": "OCR smoke set"},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["id"].startswith("ts_")
    assert payload["name"] == "Invoices"
    assert payload["document_count"] == 0

    listed = client.get("/api/test-sets")

    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["total"] == 1
    assert len(list_payload["items"]) == 1
    assert list_payload["items"][0]["id"] == payload["id"]


def test_get_and_delete_test_set(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Receipts", "description": None}).json()
    test_set_id = created["id"]

    detail = client.get(f"/api/test-sets/{test_set_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == test_set_id

    deleted = client.delete(f"/api/test-sets/{test_set_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/api/test-sets/{test_set_id}")
    assert missing.status_code == 404


def test_delete_test_set_persists_cleanup_outbox_when_storage_cleanup_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post("/api/test-sets", json={"name": "Receipts", "description": None}).json()
    test_set_id = created["id"]

    async def _boom(_test_set_id: str) -> None:
        raise RuntimeError("storage cleanup failed")

    assert isinstance(client.app, FastAPI)
    storage = client.app.state.test_set_storage
    original_delete = storage.delete_test_set
    monkeypatch.setattr(storage, "delete_test_set", _boom)

    deleted = client.delete(f"/api/test-sets/{test_set_id}")
    assert deleted.status_code == 204
    assert deleted.headers["x-cleanup-status"] == "pending"
    cleanup_job_id = deleted.headers["x-cleanup-job-id"]

    missing = client.get(f"/api/test-sets/{test_set_id}")
    assert missing.status_code == 404
    repository = client.app.state.test_set_repository
    job = asyncio.run(repository.get_storage_cleanup_job(cleanup_job_id))
    assert isinstance(job, StorageCleanupJob)
    assert job.status == "failed"
    assert job.error_code == "STORAGE_DELETE_FAILED"

    monkeypatch.setattr(storage, "delete_test_set", original_delete)
    completed, failed = asyncio.run(
        retry_pending_storage_cleanups(
            repository=repository,
            storage=storage,
        )
    )
    assert (completed, failed) == (1, 0)
    retried_job = asyncio.run(repository.get_storage_cleanup_job(cleanup_job_id))
    assert retried_job is not None
    assert retried_job.status == "completed"


def test_upload_list_detail_download_and_delete_document(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Documents", "description": None}).json()
    test_set_id = created["id"]

    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )

    assert uploaded.status_code == 201
    upload_payload = uploaded.json()
    assert upload_payload["status"] == "success"
    assert upload_payload["summary"] == {"total": 1, "succeeded": 1, "failed": 0}
    assert upload_payload["errors"] == []
    assert len(upload_payload["uploaded"]) == 1
    document_id = upload_payload["uploaded"][0]["id"]

    listed = client.get(f"/api/test-sets/{test_set_id}/documents")
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["id"] == document_id
    assert list_payload["items"][0]["has_ground_truth"] is False
    assert list_payload["items"][0]["gt_version_count"] == 0

    detail = client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == document_id

    file_response = client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}/file")
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "application/pdf"
    assert file_response.content == b"%PDF-1.4 fake"

    deleted = client.delete(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    assert missing.status_code == 404


def test_deletion_impact_blocks_active_evaluation_runs(client: TestClient) -> None:
    created = client.post(
        "/api/test-sets",
        json={"name": "Protected", "description": None},
    ).json()
    test_set_id = created["id"]
    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    ).json()
    document_id = uploaded["uploaded"][0]["id"]

    empty_impact = client.get(f"/api/test-sets/{test_set_id}/deletion-impact")
    assert empty_impact.status_code == 200
    assert empty_impact.json() == {
        "test_set_id": test_set_id,
        "can_delete": True,
        "documents": 1,
        "ground_truth_versions": 0,
        "evaluation_runs": 0,
        "active_evaluation_runs": 0,
        "evaluation_results": 0,
    }

    assert isinstance(client.app, FastAPI)
    repository = client.app.state.test_set_repository

    async def _seed_active_evaluation() -> None:
        async with repository._session_factory() as session:
            session.add(
                EvaluationRun(
                    id="eval_active_delete_impact",
                    test_set_id=test_set_id,
                    workspace_id="ws_test_set_api",
                    workflow_id="wf_delete_impact",
                    status="running",
                    total_documents=1,
                )
            )
            session.add(
                EvaluationResult(
                    id="eval_result_delete_impact",
                    evaluation_run_id="eval_active_delete_impact",
                    document_id=document_id,
                    status="pending",
                )
            )
            await session.commit()

    asyncio.run(_seed_active_evaluation())

    test_set_impact = client.get(f"/api/test-sets/{test_set_id}/deletion-impact")
    document_impact = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/deletion-impact"
    )
    assert test_set_impact.json()["can_delete"] is False
    assert test_set_impact.json()["active_evaluation_runs"] == 1
    assert document_impact.json() == {
        "document_id": document_id,
        "can_delete": False,
        "ground_truth_versions": 0,
        "evaluation_results": 1,
        "active_evaluation_runs": 1,
    }

    document_delete = client.delete(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    test_set_delete = client.delete(f"/api/test-sets/{test_set_id}")
    assert document_delete.status_code == 409
    assert document_delete.json()["error_code"] == "DOCUMENT_IN_USE"
    assert test_set_delete.status_code == 409
    assert test_set_delete.json()["error_code"] == "TEST_SET_IN_USE"


def test_delete_document_persists_cleanup_outbox_when_storage_cleanup_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post("/api/test-sets", json={"name": "Documents", "description": None}).json()
    test_set_id = created["id"]

    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    async def _boom(_storage_path: str) -> None:
        raise RuntimeError("storage cleanup failed")

    assert isinstance(client.app, FastAPI)
    monkeypatch.setattr(client.app.state.test_set_storage, "delete_document", _boom)

    deleted = client.delete(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    assert deleted.status_code == 204
    assert deleted.headers["x-cleanup-status"] == "pending"
    cleanup_job_id = deleted.headers["x-cleanup-job-id"]

    missing = client.get(f"/api/test-sets/{test_set_id}/documents/{document_id}")
    assert missing.status_code == 404
    job = asyncio.run(client.app.state.test_set_repository.get_storage_cleanup_job(cleanup_job_id))
    assert job is not None
    assert job.status == "failed"


def test_upload_reports_unsupported_files_without_failing_entire_request(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/test-sets",
        json={"name": "Mixed Upload", "description": None},
    ).json()
    test_set_id = created["id"]

    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[
            ("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf")),
            ("files", ("notes.txt", b"hello", "text/plain")),
        ],
    )

    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert len(payload["uploaded"]) == 1
    assert len(payload["errors"]) == 1
    assert payload["status"] == "partial"
    assert payload["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    assert [item["status"] for item in payload["items"]] == ["succeeded", "failed"]
    assert payload["errors"][0]["filename"] == "notes.txt"
    assert payload["errors"][0]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_document_file_disposition_inline_returns_inline_header(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Preview", "description": None}).json()
    test_set_id = created["id"]

    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("report.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    response = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/file?disposition=inline",
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "inline"
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"%PDF-1.4 fake"


def test_document_file_default_disposition_preserves_attachment_header(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Download", "description": None}).json()
    test_set_id = created["id"]

    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    response = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/file",
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="invoice.pdf"'

    response_explicit = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/file?disposition=attachment",
    )
    assert response_explicit.status_code == 200
    assert response_explicit.headers["content-disposition"] == 'attachment; filename="invoice.pdf"'

    response_invalid = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/file?disposition=bogus",
    )
    assert response_invalid.status_code == 200
    assert response_invalid.headers["content-disposition"] == 'attachment; filename="invoice.pdf"'


@pytest.mark.parametrize(
    ("filename", "mime_type", "image_format"),
    [
        ("photo.jpg", "image/jpeg", "JPEG"),
        ("scan.png", "image/png", "PNG"),
        ("page.webp", "image/webp", "WEBP"),
        ("report.pdf", "application/pdf", "PDF"),
    ],
)
def test_document_thumbnail_returns_bounded_cached_webp(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    mime_type: str,
    image_format: str,
) -> None:
    if image_format == "PDF":
        monkeypatch.setattr(
            "app.services.document_thumbnail._convert_pdf_first_page",
            lambda _content: Image.new("RGB", (800, 400), "navy"),
        )

    created = client.post("/api/test-sets", json={"name": "Thumbnails", "description": None}).json()
    test_set_id = created["id"]
    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", (filename, _image_bytes(image_format), mime_type))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    response = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=96",
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, max-age=86400, immutable"
    assert response.headers["vary"] == "Cookie"
    with Image.open(BytesIO(response.content)) as image:
        assert image.format == "WEBP"
        assert image.width <= 96
        assert image.height <= 96

    def _should_not_regenerate(*_args: object) -> bytes:
        raise AssertionError("cached thumbnail should be reused")

    monkeypatch.setattr(
        "app.api.test_documents.generate_document_thumbnail",
        _should_not_regenerate,
    )
    cached = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=96",
    )
    assert cached.status_code == 200
    assert cached.content == response.content


def test_document_thumbnail_validates_size_and_reports_generation_errors(
    client: TestClient,
) -> None:
    created = client.post("/api/test-sets", json={"name": "Broken", "description": None}).json()
    test_set_id = created["id"]
    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("broken.png", b"not an image", "image/png"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    invalid_size = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=100",
    )
    broken = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=96",
    )

    assert invalid_size.status_code == 422
    assert broken.status_code == 422
    assert broken.json()["error_code"] == "REQUEST_VALIDATION_FAILED"
    assert broken.json()["message"] == "Document thumbnail could not be generated"


def test_document_thumbnail_reports_unsupported_type(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/test-sets",
        json={"name": "Unsupported", "description": None},
    ).json()
    test_set_id = created["id"]
    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("page.png", _image_bytes("PNG"), "image/png"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]

    def _unsupported(*_args: object) -> bytes:
        raise UnsupportedThumbnailMimeTypeError("unsupported")

    monkeypatch.setattr("app.api.test_documents.generate_document_thumbnail", _unsupported)
    response = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=96",
    )

    assert response.status_code == 415
    assert response.json()["error_code"] == "UNSUPPORTED_FORMAT"
    assert response.json()["message"] == "Thumbnail not supported for this file type"


def test_delete_document_removes_cached_thumbnails(client: TestClient) -> None:
    created = client.post("/api/test-sets", json={"name": "Cleanup", "description": None}).json()
    test_set_id = created["id"]
    uploaded = client.post(
        f"/api/test-sets/{test_set_id}/documents/upload",
        files=[("files", ("page.png", _image_bytes("PNG"), "image/png"))],
    )
    document_id = uploaded.json()["uploaded"][0]["id"]
    response = client.get(
        f"/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail?size=640",
    )
    assert response.status_code == 200

    assert isinstance(client.app, FastAPI)
    storage = client.app.state.test_set_storage
    assert asyncio.run(storage.read_thumbnail(test_set_id, document_id, 640)) is not None

    deleted = client.delete(f"/api/test-sets/{test_set_id}/documents/{document_id}")

    assert deleted.status_code == 204
    assert asyncio.run(storage.read_thumbnail(test_set_id, document_id, 640)) is None
