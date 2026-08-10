from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.errors import EngineError, ErrorCode
from app.models.db.evaluation_dispatch_outbox import (
    DISPATCH_CANCELLED,
    DISPATCH_PENDING,
    DISPATCH_PUBLISHED,
)
from app.models.db.evaluation_result import EvaluationResult
from app.models.db.evaluation_run import EvaluationRun
from app.models.db.task_run import TaskRun
from app.models.execution import NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.dag_scheduler import DAGNode, DAGRunResult, NodeExecutor
from app.services.evaluation_outbox_publisher import EvaluationOutboxPublisher


async def _build_repositories(
    tmp_path: Path,
) -> tuple[
    TestSetRepository,
    EvaluationRepository,
    EvaluationDispatchRepository,
    async_sessionmaker[Any],
]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return (
        TestSetRepository(session_factory=session_factory),
        EvaluationRepository(session_factory=session_factory),
        EvaluationDispatchRepository(session_factory=session_factory),
        session_factory,
    )


async def _seed_queue_run(
    tmp_path: Path,
    *,
    document_count: int = 1,
    workspace_id: str = "ws_eval",
) -> tuple[
    TestSetRepository,
    EvaluationRepository,
    EvaluationDispatchRepository,
    async_sessionmaker[Any],
    EvaluationRun,
    list[EvaluationResult],
    list[str],
]:
    test_sets, evaluations, dispatch, session_factory = await _build_repositories(tmp_path)
    test_set = await test_sets.create_test_set(
        name="Eval set",
        description=None,
        workspace_id=workspace_id,
    )
    document_ids: list[str] = []
    for index in range(document_count):
        document = await test_sets.create_test_document(
            test_set_id=test_set.id,
            filename=f"doc-{index}.pdf",
            mime_type="application/pdf",
            storage_path=f"test_sets/{test_set.id}/doc-{index}.pdf",
            size_bytes=10,
            page_count=1,
        )
        document_ids.append(document.id)
    workflow_snapshot = {
        "nodes": [
            {"id": "input_1", "type": "input/file", "config": {}},
            {"id": "engine_1", "type": "engine/ocr", "config": {"engine_type": "ocr"}},
            {"id": "end_1", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input_1", "target": "engine_1"},
            {"source": "engine_1", "target": "end_1"},
        ],
    }
    run, results = await evaluations.create_run_with_results(
        test_set_id=test_set.id,
        workflow_id="wf_eval",
        workflow_version=1,
        workflow_snapshot_json=workflow_snapshot,
        name="Eval run",
        total_documents=document_count,
        document_ids=document_ids,
        workspace_id=workspace_id,
        queue_mode=True,
    )
    return test_sets, evaluations, dispatch, session_factory, run, results, document_ids


def _workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/file"),
            WorkflowNode(id="engine_1", type="engine/ocr", config={"engine_type": "ocr"}),
            WorkflowNode(id="end_1", type="end/final"),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="end_1"),
        ],
    )


class _StubExecutor:
    """Stand-in NodeExecutor that returns a fixed NodeOutput per engine node."""

    def __init__(self, output: NodeOutput) -> None:
        self._output = output
        self.calls = 0

    async def __call__(self, node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
        self.calls += 1
        return self._output


def _patch_executor_factory(monkeypatch: pytest.MonkeyPatch, executor: NodeExecutor) -> None:
    """Force the worker to use the supplied executor instead of an HTTP engine call."""
    from app.services import durable_workflow_execution as dwe_mod
    from app.services import engine_client as ec_mod

    async def _no_close(self: object) -> None:
        return None

    async def _run_with_executor(
        self: dwe_mod.DurableWorkflowExecutionService,
        workflow: WorkflowDefinition,
        *,
        task_id: str,
        input_bindings: dict[str, Any],
        workspace_id: str,
        cancel_check: Any = None,
        node_executor: Any = None,
    ) -> DAGRunResult:
        return await self._dag_scheduler.run(
            workflow,
            node_executor=executor,
            run_id=task_id,
            input_bindings=input_bindings,
            cancel_check=cancel_check,
        )

    monkeypatch.setattr(dwe_mod.DurableWorkflowExecutionService, "execute", _run_with_executor)
    monkeypatch.setattr(ec_mod.EngineClient, "close", _no_close)


def test_publisher_publishes_claimed_rows_and_marks_published(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, _ev, _disp, _sf, _run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=2
        )
        repository = EvaluationDispatchRepository(
            session_factory=async_sessionmaker(
                bind=create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pub.sqlite3'}"),
                expire_on_commit=False,
            )
        )
        # Re-bind to the same engine the seed used so the publisher can see the rows.
        seed_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval.sqlite3'}")
        repository = EvaluationDispatchRepository(
            session_factory=async_sessionmaker(bind=seed_engine, expire_on_commit=False)
        )

        sent: list[tuple[str, str]] = []

        def fake_send(task_id: str, result_id: str) -> None:
            sent.append((task_id, result_id))

        publisher = EvaluationOutboxPublisher(
            celery_app=object(),  # type: ignore[arg-type]
            repository=repository,
            send_task=fake_send,
        )
        published = await publisher.publish_once()
        assert published == 2
        assert {result_id for _, result_id in sent} == {r.id for r in results}
        for row in await repository.list_for_run(_run_obj.id):
            assert row.status == DISPATCH_PUBLISHED
        await seed_engine.dispose()

    asyncio.run(_run())


def test_publisher_marks_publish_failed_when_send_task_raises(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, _ev, _disp, _sf, run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=1
        )
        seed_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval.sqlite3'}")
        repository = EvaluationDispatchRepository(
            session_factory=async_sessionmaker(bind=seed_engine, expire_on_commit=False)
        )

        def failing_send(task_id: str, result_id: str) -> None:
            raise RuntimeError("broker down")

        publisher = EvaluationOutboxPublisher(
            celery_app=object(),  # type: ignore[arg-type]
            repository=repository,
            send_task=failing_send,
        )
        published = await publisher.publish_once()
        assert published == 0
        rows = await repository.list_for_run(run_obj.id)
        assert len(rows) == 1
        assert rows[0].status == DISPATCH_PENDING
        assert rows[0].last_error == "broker down"
        assert rows[0].attempt_count == 1
        await seed_engine.dispose()

    asyncio.run(_run())


def test_publisher_rechecks_cancellation_after_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, _sf, run_obj, _results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=1
        )
        seed_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval.sqlite3'}")
        repository = EvaluationDispatchRepository(
            session_factory=async_sessionmaker(bind=seed_engine, expire_on_commit=False)
        )
        original_claim_pending = repository.claim_pending

        async def claim_then_cancel(**kwargs: Any) -> list[Any]:
            rows = await original_claim_pending(**kwargs)
            cancellation = await evaluations.cancel_run(
                run_obj.id,
                workspace_id="ws_eval",
            )
            assert cancellation is not None
            return rows

        monkeypatch.setattr(repository, "claim_pending", claim_then_cancel)
        sent: list[tuple[str, str]] = []
        publisher = EvaluationOutboxPublisher(
            celery_app=object(),  # type: ignore[arg-type]
            repository=repository,
            send_task=lambda task_id, result_id: sent.append((task_id, result_id)),
        )

        assert await publisher.publish_once() == 0
        assert sent == []
        rows = await repository.list_for_run(run_obj.id)
        assert len(rows) == 1
        assert rows[0].status == DISPATCH_CANCELLED
        await seed_engine.dispose()

    asyncio.run(_run())


def test_finalize_result_marks_completed_and_completes_single_document_run(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=1
        )
        summary = await evaluations.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="OCR TEXT",
            output_format="ocr",
            processing_time_ms=42,
            error=None,
            task_run_results=[{"result_id": "res_001", "content": "OCR TEXT"}],
            task_run_node_summary={"total": 3, "completed": 3, "failed": 0},
            task_run_result_preview="OCR TEXT",
        )
        assert summary is not None
        assert summary["result_status"] == "completed"
        assert summary["run_status"] == "completed"
        assert summary["completed_count"] == 1
        assert summary["failed_count"] == 0

        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            assert stored_run is not None
            assert stored_run.status == "completed"
            assert stored_run.completed_at is not None
            assert stored_run.started_at is not None
            assert stored_run.duration_ms is not None and stored_run.duration_ms >= 0
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.output_content == "OCR TEXT"
            assert stored_result.output_format == "ocr"
            assert stored_result.processing_time_ms == 42

    asyncio.run(_run())


def test_finalize_result_marks_failed_when_outcome_is_failure(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=1
        )
        summary = await evaluations.finalize_result(
            results[0].id,
            outcome_status="failed",
            output_content=None,
            output_format=None,
            processing_time_ms=10,
            error="engine exploded",
            task_run_results=[],
            task_run_node_summary={"total": 3, "completed": 0, "failed": 3},
            task_run_result_preview=None,
        )
        assert summary is not None
        assert summary["result_status"] == "failed"
        assert summary["run_status"] == "failed"
        assert summary["failed_count"] == 1
        assert summary["completed_count"] == 0

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.error == "engine exploded"
            assert stored_result.status == "failed"

    asyncio.run(_run())


def test_finalize_result_partial_completed_for_mixed_outcomes(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, _sf, run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=2
        )
        await evaluations.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="A",
            output_format="ocr",
            processing_time_ms=1,
            error=None,
            task_run_results=[],
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
        summary = await evaluations.finalize_result(
            results[1].id,
            outcome_status="failed",
            output_content=None,
            output_format=None,
            processing_time_ms=1,
            error="boom",
            task_run_results=[],
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
        assert summary is not None
        assert summary["run_status"] == "partial_completed"
        assert summary["completed_count"] == 1
        assert summary["failed_count"] == 1
        assert run_obj.status == "partial_completed" or summary["run_status"] == "partial_completed"

    asyncio.run(_run())


def test_finalize_result_sticky_cancelled_forces_skipped(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, run_obj, results, _doc_ids = await _seed_queue_run(
            tmp_path, document_count=1
        )
        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            assert stored_run is not None
            stored_run.status = "cancelled"
            session.add(stored_run)
            await session.commit()

        summary = await evaluations.finalize_result(
            results[0].id,
            outcome_status="completed",
            output_content="late",
            output_format="ocr",
            processing_time_ms=5,
            error=None,
            task_run_results=[],
            task_run_node_summary=None,
            task_run_result_preview=None,
        )
        assert summary is not None
        assert summary["sticky_cancelled"] is True
        assert summary["result_status"] == "skipped"
        assert summary["run_status"] == "cancelled"

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.status == "skipped"
            assert stored_result.output_content is None

    asyncio.run(_run())


def test_load_result_for_execution_returns_snapshot_and_workspace(tmp_path: Path) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, _sf, run_obj, results, _doc_ids = await _seed_queue_run(tmp_path)
        snapshot = await evaluations.load_result_for_execution(results[0].id)
        assert snapshot is not None
        assert snapshot["result_id"] == results[0].id
        assert snapshot["run_id"] == run_obj.id
        assert snapshot["workspace_id"] == "ws_eval"
        assert snapshot["task_run_id"] == results[0].task_run_id
        assert isinstance(snapshot["workflow_snapshot"], dict)
        assert snapshot["document_filename"] == "doc-0.pdf"

    asyncio.run(_run())


def test_load_result_for_execution_returns_none_when_run_workspace_missing(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, _run_obj, results, _doc_ids = await _seed_queue_run(tmp_path)
        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == results[0].evaluation_run_id)
            )
            assert stored_run is not None
            stored_run.workspace_id = None
            session.add(stored_run)
            await session.commit()
        assert await evaluations.load_result_for_execution(results[0].id) is None

    asyncio.run(_run())


def test_mark_result_running_is_workspace_safe_idempotent_and_cancellation_safe(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, run, results, _doc_ids = await _seed_queue_run(
            tmp_path,
            document_count=2,
        )

        assert (
            await evaluations.mark_result_running(
                results[0].id,
                workspace_id="ws_other",
            )
            is None
        )
        assert (
            await evaluations.mark_result_running(
                results[0].id,
                workspace_id="ws_eval",
            )
            == "running"
        )

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            stored_task = await session.scalar(
                select(TaskRun).where(TaskRun.id == results[0].task_run_id)
            )
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run.id)
            )
            assert stored_result is not None
            assert stored_result.status == "running"
            assert stored_task is not None
            assert stored_task.status == "running"
            assert stored_run is not None
            assert stored_run.completed_count == 0
            assert stored_run.failed_count == 0

            stored_result.status = "completed"
            stored_task.status = "completed"
            stored_run.status = "cancelled"
            session.add_all((stored_result, stored_task, stored_run))
            await session.commit()

        assert (
            await evaluations.mark_result_running(
                results[0].id,
                workspace_id="ws_eval",
            )
            == "completed"
        )
        assert (
            await evaluations.mark_result_running(
                results[1].id,
                workspace_id="ws_eval",
            )
            == "skipped"
        )

        async with sf() as session:
            cancelled_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[1].id)
            )
            assert cancelled_result is not None
            assert cancelled_result.status == "skipped"

    asyncio.run(_run())


def test_execute_evaluation_document_async_finalizes_success_when_engine_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, _run_obj, results, _doc_ids = await _seed_queue_run(tmp_path)

        from app.services import durable_workflow_execution as dwe_mod
        from app.services.dag_scheduler import DAGRunResult

        async def _fake_execute(
            self: dwe_mod.DurableWorkflowExecutionService,
            workflow: WorkflowDefinition,
            *,
            task_id: str,
            input_bindings: dict[str, Any],
            workspace_id: str,
            cancel_check: Any = None,
            node_executor: Any = None,
        ) -> DAGRunResult:
            async with sf() as session:
                running_result = await session.scalar(
                    select(EvaluationResult).where(EvaluationResult.id == results[0].id)
                )
                running_task = await session.scalar(
                    select(TaskRun).where(TaskRun.id == results[0].task_run_id)
                )
                assert running_result is not None
                assert running_result.status == "running"
                assert running_task is not None
                assert running_task.status == "running"
            return DAGRunResult(
                completed={"engine_1": NodeOutput(text="OCR RESULT")},
                failed={},
                skipped=set(),
            )

        monkeypatch.setattr(dwe_mod.DurableWorkflowExecutionService, "execute", _fake_execute)

        from app.services import engine_client as ec_mod

        async def _no_close(self: object) -> None:
            return None

        monkeypatch.setattr(ec_mod.EngineClient, "close", _no_close)

        from app.worker_tasks import _execute_evaluation_document_async

        outcome = await _execute_evaluation_document_async(
            results[0].id,
            enable_task_retry=False,
            retry_count=0,
            max_retries=0,
            evaluation_repository=evaluations,
            node_executor=None,
        )
        assert outcome["status"] == "completed"
        assert outcome["run_status"] == "completed"

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.status == "completed"
            assert stored_result.output_content == "OCR RESULT"
            assert stored_result.output_format == "ocr"

            stored_task = await session.scalar(
                select(TaskRun).where(TaskRun.id == results[0].task_run_id)
            )
            assert stored_task is not None
            assert stored_task.status == "completed"
            assert stored_task.results_json is not None
            assert "OCR RESULT" in stored_task.results_json

    asyncio.run(_run())


def test_execute_evaluation_document_async_skips_engine_for_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate/redelivery path: a terminal result never invokes the engine."""

    async def _run() -> None:
        _ts, evaluations, _disp, sf, _run_obj, results, _doc_ids = await _seed_queue_run(tmp_path)
        async with sf() as session:
            stored = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored is not None
            stored.status = "completed"
            session.add(stored)
            await session.commit()

        executor = _StubExecutor(NodeOutput(text="SHOULD NOT RUN"))
        _patch_executor_factory(monkeypatch, executor)

        from app.worker_tasks import _execute_evaluation_document_async

        outcome = await _execute_evaluation_document_async(
            results[0].id,
            enable_task_retry=False,
            retry_count=0,
            max_retries=0,
            evaluation_repository=evaluations,
            node_executor=None,
        )
        assert outcome["status"] == "completed"
        assert executor.calls == 0

    asyncio.run(_run())


def test_execute_evaluation_document_async_finalizes_failed_when_engine_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, _run_obj, results, _doc_ids = await _seed_queue_run(tmp_path)

        from app.services import durable_workflow_execution as dwe_mod

        async def _failing_executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput:
            raise EngineError(
                error_code=ErrorCode.ENGINE_TIMEOUT,
                message="ocr timed out",
                engine_name="ocr",
            )

        async def _fake_execute(
            self: dwe_mod.DurableWorkflowExecutionService,
            workflow: WorkflowDefinition,
            *,
            task_id: str,
            input_bindings: dict[str, Any],
            workspace_id: str,
            cancel_check: Any = None,
            node_executor: Any = None,
        ) -> DAGRunResult:
            raise EngineError(
                error_code=ErrorCode.ENGINE_TIMEOUT,
                message="ocr timed out",
                engine_name="ocr",
            )

        monkeypatch.setattr(dwe_mod.DurableWorkflowExecutionService, "execute", _fake_execute)

        from app.services import engine_client as ec_mod

        async def _no_close(self: object) -> None:
            return None

        monkeypatch.setattr(ec_mod.EngineClient, "close", _no_close)

        from app.worker_tasks import _execute_evaluation_document_async

        outcome = await _execute_evaluation_document_async(
            results[0].id,
            enable_task_retry=False,
            retry_count=0,
            max_retries=0,
            evaluation_repository=evaluations,
            node_executor=None,
        )
        assert outcome["status"] == "failed"
        assert outcome["run_status"] == "failed"

        async with sf() as session:
            stored = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored is not None
            assert stored.status == "failed"
            assert stored.error is not None
            assert "ocr timed out" in stored.error

    asyncio.run(_run())


def test_execute_evaluation_document_async_handles_iteration_workflow_through_shared_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _ts, evaluations, _disp, sf, run_obj, results, document_ids = await _seed_queue_run(
            tmp_path
        )
        async with sf() as session:
            stored_run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_obj.id)
            )
            assert stored_run is not None
            stored_run.workflow_snapshot_json = json.dumps(
                {
                    "nodes": [
                        {"id": "input_1", "type": "input/file", "config": {}},
                        {
                            "id": "iter_1",
                            "type": "processor/iteration",
                            "config": {
                                "engine_node_type": "engine/ocr",
                                "engine_config": {},
                                "iterate_over": "binary",
                                "item_input_port": "image",
                                "mode": "sequential",
                                "max_concurrency": 5,
                                "error_handling": "terminate",
                            },
                        },
                        {"id": "end_1", "type": "end/final", "config": {}},
                    ],
                    "connections": [
                        {"source": "input_1", "target": "iter_1"},
                        {"source": "iter_1", "target": "end_1"},
                    ],
                }
            )
            session.add(stored_run)
            await session.commit()

        from app.services import durable_workflow_execution as dwe_mod

        async def _fake_execute(
            self: dwe_mod.DurableWorkflowExecutionService,
            workflow: WorkflowDefinition,
            *,
            task_id: str,
            input_bindings: dict[str, Any],
            workspace_id: str,
            cancel_check: Any = None,
            node_executor: Any = None,
        ) -> DAGRunResult:
            _ = (self, task_id, input_bindings, workspace_id, cancel_check, node_executor)
            assert any(node.type == "processor/iteration" for node in workflow.nodes)
            return DAGRunResult(
                completed={
                    "iter_1": NodeOutput(
                        structured={
                            "kind": "iteration_result",
                            "items": [],
                            "total": 0,
                            "success_count": 0,
                            "error_count": 0,
                        }
                    )
                },
                failed={},
                skipped=set(),
            )

        monkeypatch.setattr(dwe_mod.DurableWorkflowExecutionService, "execute", _fake_execute)

        from app.services import engine_client as ec_mod

        async def _no_close(self: object) -> None:
            return None

        monkeypatch.setattr(ec_mod.EngineClient, "close", _no_close)

        from app.worker_tasks import _execute_evaluation_document_async

        outcome = await _execute_evaluation_document_async(
            results[0].id,
            enable_task_retry=False,
            retry_count=0,
            max_retries=0,
            evaluation_repository=evaluations,
            node_executor=None,
        )
        assert outcome["status"] == "completed"

        async with sf() as session:
            stored_result = await session.scalar(
                select(EvaluationResult).where(EvaluationResult.id == results[0].id)
            )
            assert stored_result is not None
            assert stored_result.status == "completed"

    asyncio.run(_run())
