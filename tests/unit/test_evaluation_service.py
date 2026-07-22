from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.services.evaluation_service as evaluation_service_module
from app.core.feature_flags import OrchestratorMode
from app.errors import AppError, ErrorCode
from app.models.output import OutputMetadata
from app.models.task import (
    NodeState,
    NodeStatus,
    TaskContext,
    TaskInputFile,
    TaskResult,
    TaskStatus,
    WorkflowExecutionPlan,
)
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.evaluation_service import EvaluationService


def _build_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/document", config={"file": "$file_0"}),
            WorkflowNode(id="engine_1", type="engine/ocr", config={}),
            WorkflowNode(id="output_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="engine_1"),
            WorkflowConnection(source="engine_1", target="output_1"),
        ],
    )


def _build_context(*, task_id: str, content: str, duration_ms: int = 120) -> TaskContext:
    now = datetime.now(timezone.utc)
    result = TaskResult(
        result_id=f"res_{task_id}",
        format="markdown",
        filename=f"{task_id}.md",
        content_type="text/markdown",
        storage_path=f"/tmp/{task_id}.md",
        download_url=f"/api/tasks/{task_id}/results/res_{task_id}/download",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=duration_ms,
            page_count=1,
            char_count=len(content),
            word_count=max(len(content.split()), 1),
            source_filename="input.pdf",
        ),
    )
    return TaskContext(
        task_id=task_id,
        workflow=_build_workflow(),
        status=TaskStatus.COMPLETED,
        node_states={
            "input_1": NodeState(
                node_id="input_1",
                node_type="input/document",
                status=NodeStatus.COMPLETED,
            ),
            "engine_1": NodeState(
                node_id="engine_1",
                node_type="engine/ocr",
                status=NodeStatus.COMPLETED,
            ),
            "output_1": NodeState(
                node_id="output_1",
                node_type="end/final",
                status=NodeStatus.COMPLETED,
                output=result,
            ),
        },
        execution_plan=WorkflowExecutionPlan(
            total_nodes=3,
            execution_order=[["input_1"], ["engine_1"], ["output_1"]],
            parallel_groups=0,
        ),
        input_files={},
        output_result_ids={"output_1": result.result_id},
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=duration_ms,
        result=result,
    )


def _make_service(**kwargs: Any) -> EvaluationService:
    return EvaluationService(**kwargs)


def _matching_evaluation_repository(
    document_id: str = "doc_1",
) -> SimpleNamespace:
    return SimpleNamespace(
        get_result_for_task_run=AsyncMock(return_value=SimpleNamespace(document_id=document_id))
    )


@pytest.mark.asyncio
async def test_run_batch_processes_documents_sequentially_and_updates_results() -> None:
    workflow = _build_workflow()
    documents = [
        SimpleNamespace(
            id="doc_1",
            filename="invoice-1.pdf",
            mime_type="application/pdf",
            storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
            size_bytes=111,
        ),
        SimpleNamespace(
            id="doc_2",
            filename="invoice-2.pdf",
            mime_type="application/pdf",
            storage_path="test_sets/ts_1/documents/doc_2_invoice-2.pdf",
            size_bytes=222,
        ),
    ]
    pre_created_results = [
        SimpleNamespace(id="eval_result_1", document_id="doc_1"),
        SimpleNamespace(id="eval_result_2", document_id="doc_2"),
    ]
    contexts = [
        _build_context(task_id="task_eval_1", content="# First"),
        _build_context(task_id="task_eval_2", content="# Second", duration_ms=240),
    ]

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(side_effect=documents),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=pre_created_results),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(side_effect=contexts),
        wait_for_completion=AsyncMock(side_effect=contexts),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    assert evaluation_repository.mark_result_running.await_count == 2
    assert evaluation_repository.mark_result_running.await_args_list[0].args == ("eval_result_1",)
    assert evaluation_repository.mark_result_running.await_args_list[1].args == ("eval_result_2",)
    assert orchestrator.create_from_workflow.await_count == 2
    first_call = orchestrator.create_from_workflow.await_args_list[0]
    second_call = orchestrator.create_from_workflow.await_args_list[1]
    assert first_call.kwargs["source"] == "evaluation"
    assert first_call.kwargs["evaluation_run_id"] == "eval_run_1"
    storage_root = Path(evaluation_service_module.get_settings().storage_root)
    assert first_call.kwargs["input_bindings"] == {
        "input_1": TaskInputFile(
            file_path=str(storage_root / documents[0].storage_path),
            filename=documents[0].filename,
            mime_type=documents[0].mime_type,
            size_bytes=documents[0].size_bytes,
        )
    }
    assert second_call.kwargs["input_bindings"] == {
        "input_1": TaskInputFile(
            file_path=str(storage_root / documents[1].storage_path),
            filename=documents[1].filename,
            mime_type=documents[1].mime_type,
            size_bytes=documents[1].size_bytes,
        )
    }
    assert orchestrator.wait_for_completion.await_args_list[0].args == ("task_eval_1",)
    assert orchestrator.wait_for_completion.await_args_list[1].args == ("task_eval_2",)
    assert evaluation_repository.update_result.await_args_list[0].kwargs == {
        "task_run_id": "task_eval_1",
        "status": "completed",
        "output_content": "# First",
        "output_format": "markdown",
        "processing_time_ms": 120,
        "error": None,
        "workspace_id": None,
    }
    assert evaluation_repository.update_result.await_args_list[1].kwargs == {
        "task_run_id": "task_eval_2",
        "status": "completed",
        "output_content": "# Second",
        "output_format": "markdown",
        "processing_time_ms": 240,
        "error": None,
        "workspace_id": None,
    }
    final_update = evaluation_repository.update_run.await_args_list[-1].kwargs
    assert final_update["status"] == "completed"
    assert final_update["completed_count"] == 2
    assert final_update["failed_count"] == 0
    assert final_update["duration_ms"] == 360
    assert final_update["started_at"] is not None
    assert final_update["completed_at"] is not None
    assert final_update["completed_at"] >= final_update["started_at"]


@pytest.mark.asyncio
async def test_run_batch_marks_document_failed_and_continues_on_error() -> None:
    workflow = _build_workflow()
    documents = [
        SimpleNamespace(
            id="doc_1",
            filename="invoice-1.pdf",
            mime_type="application/pdf",
            storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
            size_bytes=111,
        ),
        SimpleNamespace(
            id="doc_2",
            filename="invoice-2.pdf",
            mime_type="application/pdf",
            storage_path="test_sets/ts_1/documents/doc_2_invoice-2.pdf",
            size_bytes=222,
        ),
    ]
    pre_created_results = [
        SimpleNamespace(id="eval_result_1", document_id="doc_1"),
        SimpleNamespace(id="eval_result_2", document_id="doc_2"),
    ]
    created_contexts = [
        _build_context(task_id="task_eval_1", content="# First"),
        _build_context(task_id="task_eval_2", content="# Never returned"),
    ]
    completed_context = _build_context(task_id="task_eval_1", content="# First")

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(side_effect=documents),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=pre_created_results),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(side_effect=created_contexts),
        wait_for_completion=AsyncMock(
            side_effect=[completed_context, RuntimeError("engine timeout")]
        ),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    assert evaluation_repository.update_result.await_args_list[0].kwargs["status"] == "completed"
    assert evaluation_repository.update_result.await_args_list[1].kwargs == {
        "task_run_id": "task_eval_2",
        "status": "failed",
        "output_content": None,
        "output_format": None,
        "processing_time_ms": None,
        "error": "engine timeout",
        "workspace_id": None,
    }
    final_update = evaluation_repository.update_run.await_args_list[-1].kwargs
    assert final_update["status"] == "completed"
    assert final_update["completed_count"] == 1
    assert final_update["failed_count"] == 1
    assert final_update["duration_ms"] == 120
    assert final_update["started_at"] is not None
    assert final_update["completed_at"] is not None
    assert final_update["completed_at"] >= final_update["started_at"]


@pytest.mark.asyncio
async def test_run_batch_sets_started_and_completed_timestamps() -> None:
    workflow = _build_workflow()
    document = SimpleNamespace(
        id="doc_1",
        filename="invoice-1.pdf",
        mime_type="application/pdf",
        storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
        size_bytes=111,
    )
    pre_created_result = SimpleNamespace(id="eval_result_1", document_id="doc_1")
    context = _build_context(task_id="task_eval_1", content="# First", duration_ms=120)

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(return_value=document),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=[pre_created_result]),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(return_value=context),
        wait_for_completion=AsyncMock(return_value=context),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    first_update = evaluation_repository.update_run.await_args_list[0].kwargs
    final_update = evaluation_repository.update_run.await_args_list[-1].kwargs

    assert first_update["status"] == "running"
    assert first_update["started_at"] is not None
    assert first_update["completed_at"] is None
    assert final_update["status"] == "completed"
    assert final_update["started_at"] == first_update["started_at"]
    assert final_update["completed_at"] is not None
    assert final_update["completed_at"] >= first_update["started_at"]


@pytest.mark.asyncio
async def test_run_batch_marks_run_running_before_processing_first_document() -> None:
    workflow = _build_workflow()
    document = SimpleNamespace(
        id="doc_1",
        filename="invoice-1.pdf",
        mime_type="application/pdf",
        storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
        size_bytes=111,
    )
    pre_created_result = SimpleNamespace(id="eval_result_1", document_id="doc_1")
    created_context = _build_context(task_id="task_eval_1", content="# First", duration_ms=120)
    completion_event = asyncio.Event()

    async def _wait_for_completion(*args: object, **kwargs: object) -> TaskContext:
        _ = args, kwargs
        await completion_event.wait()
        return created_context

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(return_value=document),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=[pre_created_result]),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(return_value=created_context),
        wait_for_completion=AsyncMock(side_effect=_wait_for_completion),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    task = asyncio.create_task(
        service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)
    )
    await asyncio.sleep(0)

    assert evaluation_repository.update_run.await_count == 1
    first_update = evaluation_repository.update_run.await_args_list[0].kwargs
    assert first_update["status"] == "running"
    assert first_update["completed_count"] == 0
    assert first_update["failed_count"] == 0
    assert first_update["started_at"] is not None
    assert first_update["completed_at"] is None

    completion_event.set()
    await task


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_uses_context_output_when_available() -> None:
    context = _build_context(task_id="task_eval_apply", content="# Applied output", duration_ms=99)
    fake_gt = SimpleNamespace(
        id="gt_1",
        document_id="doc_1",
        version=1,
        source="inference_apply",
        format="markdown",
        content="# Applied output",
        source_task_run_id="task_eval_apply",
        notes="apply",
    )
    task_run_repository = SimpleNamespace(get_snapshot=AsyncMock(return_value=None))
    ground_truth_repository = SimpleNamespace(create_version=AsyncMock(return_value=fake_gt))
    orchestrator = SimpleNamespace(wait_for_completion=AsyncMock(return_value=context))
    service = _make_service(
        orchestrator=orchestrator,
        task_run_repository=task_run_repository,
        ground_truth_repository=ground_truth_repository,
        evaluation_repository=_matching_evaluation_repository(),
    )

    result = await service.apply_result_as_ground_truth(
        document_id="doc_1",
        task_run_id="task_eval_apply",
        notes="apply",
        workspace_id="ws_eval",
        requested_by_user_id="usr_eval",
    )

    ground_truth_repository.create_version.assert_awaited_once_with(
        document_id="doc_1",
        source="inference_apply",
        format="markdown",
        content="# Applied output",
        source_task_run_id="task_eval_apply",
        notes="apply",
        workspace_id="ws_eval",
    )
    orchestrator.wait_for_completion.assert_awaited_once_with(
        "task_eval_apply",
        timeout=300.0,
        workspace_id="ws_eval",
    )
    assert result is fake_gt, (
        "apply_result_as_ground_truth must return the created GroundTruth record"
    )


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_falls_back_to_task_snapshot_results() -> None:
    snapshot = SimpleNamespace(
        results=[
            {
                "result_id": "res_fallback",
                "output_format": "text",
                "content": "fallback content",
                "file": {
                    "storage_path": "/tmp/fallback.txt",
                    "filename": "fallback.txt",
                    "content_type": "text/plain",
                },
            }
        ]
    )
    context_without_outputs = _build_context(task_id="task_eval_apply", content="unused")
    context_without_outputs.output_result_ids = {}
    context_without_outputs.result = None
    context_without_outputs.node_states["output_1"].output = None
    fake_gt = SimpleNamespace(
        id="gt_fb",
        document_id="doc_1",
        version=1,
        source="inference_apply",
        format="text",
        content="fallback content",
        source_task_run_id="task_eval_apply",
        notes=None,
    )
    task_run_repository = SimpleNamespace(get_snapshot=AsyncMock(return_value=snapshot))
    ground_truth_repository = SimpleNamespace(create_version=AsyncMock(return_value=fake_gt))
    orchestrator = SimpleNamespace(
        wait_for_completion=AsyncMock(return_value=context_without_outputs)
    )
    service = _make_service(
        orchestrator=orchestrator,
        task_run_repository=task_run_repository,
        ground_truth_repository=ground_truth_repository,
        evaluation_repository=_matching_evaluation_repository(),
    )

    result = await service.apply_result_as_ground_truth(
        document_id="doc_1",
        task_run_id="task_eval_apply",
        notes=None,
        workspace_id="ws_eval",
        requested_by_user_id="usr_eval",
    )

    ground_truth_repository.create_version.assert_awaited_once_with(
        document_id="doc_1",
        source="inference_apply",
        format="text",
        content="fallback content",
        source_task_run_id="task_eval_apply",
        notes=None,
        workspace_id="ws_eval",
    )
    task_run_repository.get_snapshot.assert_awaited_once_with(
        "task_eval_apply",
        workspace_id="ws_eval",
        expected_workspace_id="ws_eval",
    )
    assert result is fake_gt, (
        "apply_result_as_ground_truth must return the created GroundTruth record"
    )


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_falls_back_to_snapshot_when_context_missing() -> None:
    snapshot = SimpleNamespace(
        results=[
            {
                "result_id": "res_missing_context",
                "output_format": "markdown",
                "content": "# Snapshot output",
                "file": {
                    "storage_path": "/tmp/snapshot.md",
                    "filename": "snapshot.md",
                    "content_type": "text/markdown",
                },
            }
        ]
    )
    fake_gt = SimpleNamespace(
        id="gt_snapshot",
        document_id="doc_1",
        version=2,
        source="inference_apply",
        format="markdown",
        content="# Snapshot output",
        source_task_run_id="task_eval_apply",
        notes="from snapshot",
    )
    task_run_repository = SimpleNamespace(get_snapshot=AsyncMock(return_value=snapshot))
    ground_truth_repository = SimpleNamespace(create_version=AsyncMock(return_value=fake_gt))
    orchestrator = SimpleNamespace(
        wait_for_completion=AsyncMock(side_effect=KeyError("task_eval_apply"))
    )
    service = _make_service(
        orchestrator=orchestrator,
        task_run_repository=task_run_repository,
        ground_truth_repository=ground_truth_repository,
        evaluation_repository=_matching_evaluation_repository(),
    )

    result = await service.apply_result_as_ground_truth(
        document_id="doc_1",
        task_run_id="task_eval_apply",
        notes="from snapshot",
        workspace_id="ws_eval",
        requested_by_user_id="usr_eval",
    )

    ground_truth_repository.create_version.assert_awaited_once_with(
        document_id="doc_1",
        source="inference_apply",
        format="markdown",
        content="# Snapshot output",
        source_task_run_id="task_eval_apply",
        notes="from snapshot",
        workspace_id="ws_eval",
    )
    task_run_repository.get_snapshot.assert_awaited_once_with(
        "task_eval_apply",
        workspace_id="ws_eval",
        expected_workspace_id="ws_eval",
    )
    assert result is fake_gt


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_maps_missing_task_to_404() -> None:
    service = _make_service(
        orchestrator=SimpleNamespace(
            wait_for_completion=AsyncMock(side_effect=KeyError("task_missing"))
        ),
        task_run_repository=SimpleNamespace(get_snapshot=AsyncMock(return_value=None)),
        ground_truth_repository=SimpleNamespace(create_version=AsyncMock()),
        evaluation_repository=_matching_evaluation_repository(),
    )

    with pytest.raises(AppError) as caught:
        await service.apply_result_as_ground_truth(
            document_id="doc_1",
            task_run_id="task_missing",
            notes=None,
            workspace_id="ws_eval",
            requested_by_user_id="usr_eval",
        )

    assert caught.value.error_code is ErrorCode.TASK_NOT_FOUND
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_maps_empty_snapshot_to_409() -> None:
    service = _make_service(
        orchestrator=SimpleNamespace(
            wait_for_completion=AsyncMock(side_effect=KeyError("task_pending"))
        ),
        task_run_repository=SimpleNamespace(
            get_snapshot=AsyncMock(return_value=SimpleNamespace(results=[]))
        ),
        ground_truth_repository=SimpleNamespace(create_version=AsyncMock()),
        evaluation_repository=_matching_evaluation_repository(),
    )

    with pytest.raises(AppError) as caught:
        await service.apply_result_as_ground_truth(
            document_id="doc_1",
            task_run_id="task_pending",
            notes=None,
            workspace_id="ws_eval",
            requested_by_user_id="usr_eval",
        )

    assert caught.value.error_code is ErrorCode.TASK_RESULT_NOT_READY
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_hides_another_users_live_task() -> None:
    context = _build_context(task_id="task_other", content="secret")
    context.requested_by_user_id = "usr_other"
    snapshot_repository = SimpleNamespace(get_snapshot=AsyncMock())
    ground_truth_repository = SimpleNamespace(create_version=AsyncMock())
    service = _make_service(
        orchestrator=SimpleNamespace(wait_for_completion=AsyncMock(return_value=context)),
        task_run_repository=snapshot_repository,
        ground_truth_repository=ground_truth_repository,
        evaluation_repository=_matching_evaluation_repository(),
    )

    with pytest.raises(AppError) as caught:
        await service.apply_result_as_ground_truth(
            document_id="doc_1",
            task_run_id="task_other",
            notes=None,
            workspace_id="ws_eval",
            requested_by_user_id="usr_eval",
        )

    assert caught.value.error_code is ErrorCode.TASK_NOT_FOUND
    snapshot_repository.get_snapshot.assert_not_awaited()
    ground_truth_repository.create_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_result_as_ground_truth_rejects_another_documents_task() -> None:
    orchestrator = SimpleNamespace(wait_for_completion=AsyncMock())
    ground_truth_repository = SimpleNamespace(create_version=AsyncMock())
    service = _make_service(
        orchestrator=orchestrator,
        task_run_repository=SimpleNamespace(get_snapshot=AsyncMock()),
        ground_truth_repository=ground_truth_repository,
        evaluation_repository=_matching_evaluation_repository("doc_other"),
    )

    with pytest.raises(AppError) as caught:
        await service.apply_result_as_ground_truth(
            document_id="doc_1",
            task_run_id="task_other_document",
            notes=None,
            workspace_id="ws_eval",
            requested_by_user_id="usr_eval",
        )

    assert caught.value.error_code is ErrorCode.TASK_NOT_FOUND
    orchestrator.wait_for_completion.assert_not_awaited()
    ground_truth_repository.create_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_batch_marks_run_failed_when_all_results_fail() -> None:
    """When all documents fail, the run status should be 'failed', not 'completed'."""
    workflow = _build_workflow()
    document = SimpleNamespace(
        id="doc_1",
        filename="bad.pdf",
        mime_type="application/pdf",
        storage_path="test_sets/ts_1/documents/doc_1_bad.pdf",
        size_bytes=111,
    )
    pre_created_result = SimpleNamespace(id="eval_result_1", document_id="doc_1")

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(return_value=document),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=[pre_created_result]),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(
            return_value=_build_context(task_id="task_eval_1", content="# Never")
        ),
        wait_for_completion=AsyncMock(side_effect=RuntimeError("engine offline")),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    final_update = evaluation_repository.update_run.await_args_list[-1].kwargs
    assert final_update["status"] == "failed"
    assert final_update["failed_count"] == 1
    assert final_update["completed_count"] == 0


@pytest.mark.asyncio
async def test_run_batch_rejects_queue_mode_for_evaluation() -> None:
    service = _make_service(
        orchestrator=SimpleNamespace(),
        test_set_repository=SimpleNamespace(get_test_document=AsyncMock(return_value=None)),
        evaluation_repository=SimpleNamespace(
            list_results=AsyncMock(return_value=[]),
            update_run=AsyncMock(),
        ),
    )

    with pytest.raises(RuntimeError, match="serial orchestrator mode"):
        await service.run_batch(
            run_id="eval_run_1",
            test_set_id="ts_1",
            workflow=_build_workflow(),
            orchestrator_mode=OrchestratorMode.QUEUE,
        )


@pytest.mark.asyncio
async def test_run_batch_rejects_queue_mode_from_feature_flags_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evaluation_service_module.FeatureFlags,
        "get_orchestrator_mode",
        lambda: OrchestratorMode.QUEUE,
    )
    service = _make_service(
        orchestrator=SimpleNamespace(),
        test_set_repository=SimpleNamespace(get_test_document=AsyncMock(return_value=None)),
        evaluation_repository=SimpleNamespace(
            list_results=AsyncMock(return_value=[]),
            update_run=AsyncMock(),
        ),
    )

    with pytest.raises(RuntimeError, match="serial orchestrator mode"):
        await service.run_batch(
            run_id="eval_run_1",
            test_set_id="ts_1",
            workflow=_build_workflow(),
        )


@pytest.mark.asyncio
async def test_run_batch_resolves_storage_path_relative_to_storage_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings

    mock_settings = Settings(storage_root="/mock/storage/root")
    monkeypatch.setattr(evaluation_service_module, "get_settings", lambda: mock_settings)

    workflow = _build_workflow()
    document = SimpleNamespace(
        id="doc_1",
        filename="invoice-1.pdf",
        mime_type="application/pdf",
        storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
        size_bytes=111,
    )
    pre_created_result = SimpleNamespace(id="eval_result_1", document_id="doc_1")
    context = _build_context(task_id="task_eval_1", content="# First")

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(return_value=document),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=[pre_created_result]),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(return_value=context),
        wait_for_completion=AsyncMock(return_value=context),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    first_call = orchestrator.create_from_workflow.await_args_list[0]
    expected_path = str(Path("/mock/storage/root") / document.storage_path)
    assert first_call.kwargs["input_bindings"]["input_1"].file_path == expected_path


@pytest.mark.asyncio
async def test_run_batch_marks_failed_when_create_from_workflow_raises() -> None:
    workflow = _build_workflow()
    document = SimpleNamespace(
        id="doc_1",
        filename="invoice-1.pdf",
        mime_type="application/pdf",
        storage_path="test_sets/ts_1/documents/doc_1_invoice-1.pdf",
        size_bytes=111,
    )
    pre_created_result = SimpleNamespace(id="eval_result_1", document_id="doc_1")

    test_set_repository = SimpleNamespace(
        get_test_document=AsyncMock(return_value=document),
    )
    evaluation_repository = SimpleNamespace(
        list_results=AsyncMock(return_value=[pre_created_result]),
        mark_result_running=AsyncMock(return_value="running"),
        update_result=AsyncMock(),
        update_run=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        create_from_workflow=AsyncMock(side_effect=RuntimeError("test")),
    )
    service = _make_service(
        orchestrator=orchestrator,
        test_set_repository=test_set_repository,
        evaluation_repository=evaluation_repository,
    )

    await service.run_batch(run_id="eval_run_1", test_set_id="ts_1", workflow=workflow)

    update_result_kwargs = evaluation_repository.update_result.await_args_list[0].kwargs
    assert update_result_kwargs["status"] == "failed"
    assert "test" in update_result_kwargs["error"]
    assert update_result_kwargs["task_run_id"] is None
