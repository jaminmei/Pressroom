from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.test_documents import router as test_documents_router
from app.api.test_sets import router as test_sets_router
from app.db.base import Base
from app.repositories.test_set_repository import TestSetRepository
from app.storage.test_set_storage import TestSetStorage
from tests._api_workspace_contract import (
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(test_sets_router, prefix="/api")
    app.include_router(test_documents_router, prefix="/api")

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'cascade_api.sqlite3'}", future=True
    )

    async def _prepare() -> async_sessionmaker:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    repository = TestSetRepository(session_factory=asyncio.run(_prepare()))
    app.state.test_set_repository = repository
    app.state.test_set_storage = TestSetStorage(tmp_path / "storage")

    install_authenticated_workspace(app, monkeypatch)
    api_client = TestClient(app)
    try:
        yield api_client
    finally:
        remove_authenticated_workspace(app)
        asyncio.run(engine.dispose())


def test_delete_test_set_cascades_database_and_storage(client: TestClient) -> None:
    repository = client.app.state.test_set_repository
    storage = client.app.state.test_set_storage

    test_set = asyncio.run(
        repository.create_test_set(
            name="Cascade API Set",
            description=None,
            workspace_id=TEST_WORKSPACE_ID,
        )
    )

    uploaded = client.post(
        f"/api/test-sets/{test_set.id}/documents/upload",
        files=[("files", ("invoice.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["uploaded"][0]["id"]

    storage_root = Path(storage.storage_root)
    test_set_dir = storage_root / "test_sets" / test_set.id
    assert test_set_dir.exists()

    deleted = client.delete(f"/api/test-sets/{test_set.id}")
    assert deleted.status_code == 204

    missing_test_set = client.get(f"/api/test-sets/{test_set.id}")
    assert missing_test_set.status_code == 404

    missing_document = client.get(f"/api/test-sets/{test_set.id}/documents/{document_id}")
    assert missing_document.status_code == 404

    assert not test_set_dir.exists()
