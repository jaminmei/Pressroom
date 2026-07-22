from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.repositories.api_key_repository import ApiKeyRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.test_set_repository import TestSetRepository


async def _build_repositories(
    tmp_path: Path,
) -> tuple[TestSetRepository, EvaluationRepository]:
    db_path = tmp_path / "repository_workspace_filter.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    test_set_repository = TestSetRepository(session_factory=session_factory)
    evaluation_repository = EvaluationRepository(session_factory=session_factory)
    test_set_repository._test_engine = engine  # type: ignore[attr-defined]
    evaluation_repository._test_engine = engine  # type: ignore[attr-defined]
    return test_set_repository, evaluation_repository


def test_cross_workspace_repository_filters_block_reads_and_updates(tmp_path: Path) -> None:
    async def _run() -> None:
        test_set_repo, evaluation_repo = await _build_repositories(tmp_path)
        try:
            test_set_a = await test_set_repo.create_test_set(
                name="Workspace A",
                description=None,
                workspace_id="ws_A",
            )
            await test_set_repo.create_test_set(
                name="Workspace B",
                description=None,
                workspace_id="ws_B",
            )

            hidden = await test_set_repo.get_test_set(
                test_set_a.id,
                workspace_id="ws_B",
                expected_workspace_id="ws_B",
            )
            assert hidden is None

            scoped_items = await test_set_repo.list_test_sets(workspace_id="ws_A")
            assert [item.id for item in scoped_items] == [test_set_a.id]

            blocked_update = await test_set_repo.update_test_set(
                test_set_a.id,
                updates={"name": "should not land"},
                workspace_id="ws_B",
            )
            assert blocked_update is None

            run = await evaluation_repo.create_run(
                test_set_id=test_set_a.id,
                workflow_id="wf_A",
                workflow_version=1,
                workflow_snapshot_json=None,
                name="Workspace run",
                total_documents=0,
                workspace_id="ws_A",
            )

            blocked_run = await evaluation_repo.get_run(
                run.id,
                workspace_id="ws_B",
                expected_workspace_id="ws_B",
            )
            assert blocked_run is None
        finally:
            await test_set_repo._test_engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_api_key_repository_requires_workspace_for_management_queries() -> None:
    repository = ApiKeyRepository()

    with pytest.raises(RuntimeError, match="workspace_id required"):
        asyncio.run(
            repository.create(
                id="key_missing_workspace",
                key_hash="hash",
                key_prefix="dca_missing",
                workflow_id="wf_missing_workspace",
            )
        )

    with pytest.raises(RuntimeError, match="workspace_id required"):
        asyncio.run(repository.list_by_workflow("wf_missing_workspace"))
