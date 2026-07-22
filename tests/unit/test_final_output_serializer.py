from __future__ import annotations

from app.models.execution import NodeOutput
from app.models.output import OutputMetadata
from app.models.task import TaskResult
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.final_output_serializer import build_final_output_snapshot_entries


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="engine_a", type="engine/ocr"),
            WorkflowNode(id="engine_b", type="engine/text"),
            WorkflowNode(id="end", type="end/final"),
        ],
        connections=[
            WorkflowConnection(source="engine_b", target="end"),
            WorkflowConnection(source="engine_a", target="end"),
        ],
    )


def _task_result(result_id: str, content: str) -> TaskResult:
    return TaskResult(
        result_id=result_id,
        format="markdown",
        filename=f"{result_id}.md",
        content_type="text/markdown",
        storage_path="",
        download_url=f"/download/{result_id}",
        content=content,
        metadata=OutputMetadata(
            processing_time_ms=12,
            page_count=1,
            char_count=len(content),
            word_count=len(content.split()),
            source_filename="source.pdf",
        ),
    )


def test_serializer_preserves_end_connection_order_for_serial_results() -> None:
    entries = build_final_output_snapshot_entries(
        _workflow(),
        {
            "engine_a": _task_result("result-a", "A"),
            "engine_b": _task_result("result-b", "B"),
        },
        task_id="task-serial",
        result_ids_by_node={"engine_a": "result-a", "engine_b": "result-b"},
    )

    assert [entry["result_id"] for entry in entries] == ["result-b", "result-a"]
    assert [entry["node_id"] for entry in entries] == ["engine_b", "engine_a"]


def test_serializer_normalizes_queue_node_output_to_complete_snapshot() -> None:
    entries = build_final_output_snapshot_entries(
        _workflow(),
        {
            "engine_b": NodeOutput(
                text="queue output",
                metadata={"processing_time_ms": 42, "page_count": 2},
            )
        },
        task_id="task-queue",
        task_duration_ms=100,
        source_filename="source.pdf",
    )

    assert len(entries) == 1
    assert entries[0]["result_id"] == "res_001"
    assert entries[0]["content"] == "queue output"
    assert entries[0]["duration_ms"] == 42
    assert entries[0]["metadata"] == {
        "processing_time_ms": 42,
        "page_count": 2,
        "char_count": 12,
        "word_count": 2,
    }
    assert entries[0]["file"] == {
        "filename": "source.pdf.md",
        "size_bytes": len("queue output".encode("utf-8")),
        "content_type": "text/markdown",
        "storage_path": "",
        "download_url": "/api/tasks/task-queue/results/res_001/download",
    }
