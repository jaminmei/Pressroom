from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.db.test_document import TestDocument
from app.models.db.test_set import TestSet
from app.repositories.test_set_repository import TestSetRepository

WORKSPACE_ID = "ws_test_set_repository"


async def _build_repository(tmp_path: Path) -> TestSetRepository:
    db_path = tmp_path / "test_set_repository.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    repository = TestSetRepository(session_factory=session_factory)
    repository._test_engine = engine  # type: ignore[attr-defined]
    return repository


def test_create_test_set_and_document_updates_document_count(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo = await _build_repository(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Invoices",
                description="Backend repository fixture",
                workspace_id=WORKSPACE_ID,
            )

            assert isinstance(test_set, TestSet)
            assert test_set.id.startswith("ts_")
            assert test_set.document_count == 0

            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_001_invoice.pdf",
                size_bytes=2048,
                page_count=3,
            )

            assert isinstance(document, TestDocument)
            assert document.id.startswith("doc_")
            assert document.test_set_id == test_set.id

            stored = await test_set_repo.get_test_set(
                test_set.id,
                workspace_id=WORKSPACE_ID,
            )
            assert stored is not None
            assert stored.document_count == 1

            documents = await test_set_repo.list_test_documents(
                test_set.id,
                workspace_id=WORKSPACE_ID,
            )
            assert [item.id for item in documents] == [document.id]
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_list_test_sets_returns_newest_first(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo = await _build_repository(tmp_path)
        try:
            older = await test_set_repo.create_test_set(
                name="Older",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            newer = await test_set_repo.create_test_set(
                name="Newer",
                description=None,
                workspace_id=WORKSPACE_ID,
            )

            items = await test_set_repo.list_test_sets(workspace_id=WORKSPACE_ID)
            assert [item.id for item in items[:2]] == [newer.id, older.id]
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_delete_test_document_updates_document_count(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo = await _build_repository(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Delete Doc",
                description=None,
                workspace_id=WORKSPACE_ID,
            )
            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="delete-me.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_delete_me.pdf",
                size_bytes=100,
                page_count=1,
            )

            await test_set_repo.delete_test_document(
                document.id,
                workspace_id=WORKSPACE_ID,
            )

            assert (
                await test_set_repo.get_test_document(
                    document.id,
                    workspace_id=WORKSPACE_ID,
                )
                is None
            )
            stored = await test_set_repo.get_test_set(
                test_set.id,
                workspace_id=WORKSPACE_ID,
            )
            assert stored is not None
            assert stored.document_count == 0
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_delete_test_set_removes_record(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo = await _build_repository(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Delete Set",
                description=None,
                workspace_id=WORKSPACE_ID,
            )

            await test_set_repo.delete_test_set(
                test_set.id,
                workspace_id=WORKSPACE_ID,
            )

            assert (
                await test_set_repo.get_test_set(
                    test_set.id,
                    workspace_id=WORKSPACE_ID,
                )
                is None
            )
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_create_test_document_accepts_custom_document_id(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo = await _build_repository(tmp_path)
        try:
            test_set = await test_set_repo.create_test_set(
                name="Custom ID",
                description=None,
                workspace_id=WORKSPACE_ID,
            )

            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="custom.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/custom.pdf",
                size_bytes=100,
                page_count=1,
                document_id="doc_custom123",
            )
            assert document.id == "doc_custom123"

            auto_doc = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="auto.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/auto.pdf",
                size_bytes=200,
                page_count=2,
            )
            assert auto_doc.id.startswith("doc_")
            assert auto_doc.id != "doc_custom123"
        finally:
            await test_set_repo._test_engine.dispose()

    asyncio.run(_run())
