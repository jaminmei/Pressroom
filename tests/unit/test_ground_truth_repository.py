from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository


async def _build_repositories(tmp_path: Path) -> tuple[TestSetRepository, GroundTruthRepository]:
    db_path = tmp_path / "ground_truth_repository.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    test_set_repository = TestSetRepository(session_factory=session_factory)
    ground_truth_repository = GroundTruthRepository(session_factory=session_factory)
    test_set_repository._test_engine = engine  # type: ignore[attr-defined]
    ground_truth_repository._test_engine = engine  # type: ignore[attr-defined]
    return test_set_repository, ground_truth_repository


def test_create_ground_truth_versions_is_append_only(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, ground_truth_repo = await _build_repositories(tmp_path)
        try:
            workspace_id = "workspace-gt"
            test_set = await test_set_repo.create_test_set(
                name="GT Set",
                description=None,
                workspace_id=workspace_id,
            )
            document = await test_set_repo.create_test_document(
                test_set_id=test_set.id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                storage_path=f"test_sets/{test_set.id}/documents/doc_gt_invoice.pdf",
                size_bytes=100,
                page_count=1,
            )

            first = await ground_truth_repo.create_version(
                document_id=document.id,
                source="manual_edit",
                format="text",
                content="first version",
                notes="initial",
                workspace_id=workspace_id,
            )
            second = await ground_truth_repo.create_version(
                document_id=document.id,
                source="inference_apply",
                format="markdown",
                content="# second version",
                source_task_run_id="task_eval_001",
                notes="applied",
                workspace_id=workspace_id,
            )

            assert first.version == 1
            assert second.version == 2

            latest = await ground_truth_repo.get_latest(
                document.id,
                workspace_id=workspace_id,
            )
            assert latest is not None
            assert latest.id == second.id
            assert latest.source_task_run_id == "task_eval_001"

            first_by_version = await ground_truth_repo.get_version(
                document.id,
                1,
                workspace_id=workspace_id,
            )
            assert first_by_version is not None
            assert first_by_version.id == first.id
            assert first_by_version.content == "first version"
            assert (
                await ground_truth_repo.get_version(
                    document.id,
                    1,
                    workspace_id="workspace-other",
                )
                is None
            )

            versions = await ground_truth_repo.list_versions(
                document.id,
                workspace_id=workspace_id,
            )
            assert [item.version for item in versions] == [2, 1]
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())
