"""Pure serialization helpers for workflow final-node outputs.

Serial orchestration has rich ``TaskResult`` objects while the queue worker
receives durable DAG ``NodeOutput`` values.  Keeping the conversion here
ensures both execution paths produce the same result snapshot shape and keep
the workflow connection order stable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from app.models.execution import NodeOutput
from app.models.task import TaskResult
from app.models.workflow import WorkflowDefinition

RESULT_PREVIEW_MAX_CHARS = 500


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _node_type_engine(node_type: str) -> str | None:
    if node_type.startswith("engine/"):
        return node_type.split("/", 1)[1] or None
    return None


def _final_upstream_ids(workflow: WorkflowDefinition) -> list[str]:
    end_node = next((node for node in workflow.nodes if node.type == "end/final"), None)
    if end_node is None:
        return []
    # Workflow connections are persisted in user-authored order.  Do not use
    # a set or sort here: result IDs and snapshots must remain deterministic.
    return [
        connection.source for connection in workflow.connections if connection.target == end_node.id
    ]


def _node_output_content(output: NodeOutput) -> str:
    if output.text is not None:
        return output.text
    if output.structured is not None:
        return json.dumps(output.structured, ensure_ascii=False, sort_keys=True)
    return ""


def _serialize_node_output(
    *,
    result_id: str,
    node_id: str,
    node_type: str,
    output: NodeOutput,
    task_id: str,
    task_duration_ms: int | None,
    source_filename: str | None,
) -> dict[str, object]:
    content = _node_output_content(output)
    metadata = output.metadata if isinstance(output.metadata, dict) else {}
    processing_time_ms = _safe_int(metadata.get("processing_time_ms"), task_duration_ms or 0)
    filename_value = metadata.get("filename")
    filename = (
        filename_value
        if isinstance(filename_value, str) and filename_value
        else f"{source_filename or 'output'}.md"
    )
    content_type_value = metadata.get("content_type")
    content_type = (
        content_type_value
        if isinstance(content_type_value, str) and content_type_value
        else "text/markdown"
    )
    page_count = _safe_int(metadata.get("page_count"), 1)
    char_count = _safe_int(metadata.get("char_count"), len(content))
    word_count = _safe_int(metadata.get("word_count"), len(content.split()) if content else 0)
    engine_type = _node_type_engine(node_type)
    output_format = engine_type or "markdown"
    return {
        "result_id": result_id,
        "node_id": node_id,
        "node_type": node_type,
        "engine_type": engine_type,
        "output_format": output_format,
        "result_preview": content[:RESULT_PREVIEW_MAX_CHARS],
        "duration_ms": processing_time_ms,
        "status": "completed",
        "file": {
            "filename": filename,
            "size_bytes": len(content.encode("utf-8")),
            "content_type": content_type,
            "storage_path": "",
            "download_url": f"/api/tasks/{task_id}/results/{result_id}/download",
        },
        "metadata": {
            "processing_time_ms": processing_time_ms,
            "page_count": page_count,
            "char_count": char_count,
            "word_count": word_count,
        },
        "content": content,
    }


def _serialize_task_result(
    *,
    result: TaskResult,
    node_id: str,
    node_type: str,
    task_duration_ms: int | None,
) -> dict[str, object]:
    duration_ms = result.metadata.processing_time_ms or task_duration_ms or 0
    engine_type = _node_type_engine(node_type)
    return {
        "result_id": result.result_id,
        "node_id": node_id,
        "node_type": node_type,
        "engine_type": engine_type,
        "output_format": engine_type or "markdown",
        "result_preview": result.content[:RESULT_PREVIEW_MAX_CHARS],
        "duration_ms": duration_ms,
        "status": "completed",
        "file": {
            "filename": result.filename,
            "size_bytes": len(result.content.encode("utf-8")),
            "content_type": result.content_type,
            "storage_path": result.storage_path,
            "download_url": result.download_url,
        },
        "metadata": {
            "processing_time_ms": result.metadata.processing_time_ms,
            "page_count": result.metadata.page_count,
            "char_count": result.metadata.char_count,
            "word_count": result.metadata.word_count,
        },
        "content": result.content,
    }


def build_final_output_snapshot_entries(
    workflow: WorkflowDefinition,
    outputs_by_node: Mapping[str, object],
    *,
    task_id: str,
    task_duration_ms: int | None = None,
    result_ids_by_node: Mapping[str, str] | None = None,
    source_filename: str | None = None,
) -> list[dict[str, object]]:
    """Serialize outputs connected to ``end/final`` in connection order."""
    entries: list[dict[str, object]] = []
    seen_result_ids: set[str] = set()
    result_ids = result_ids_by_node or {}

    for index, node_id in enumerate(_final_upstream_ids(workflow), start=1):
        output = outputs_by_node.get(node_id)
        if not isinstance(output, (TaskResult, NodeOutput)):
            continue
        result_id = result_ids.get(node_id, f"res_{index:03d}")
        if result_id in seen_result_ids:
            continue
        seen_result_ids.add(result_id)
        node = workflow.get_node(node_id)
        node_type = node.type if node is not None else "engine/unknown"
        if isinstance(output, TaskResult):
            entries.append(
                _serialize_task_result(
                    result=output,
                    node_id=node_id,
                    node_type=node_type,
                    task_duration_ms=task_duration_ms,
                )
            )
        else:
            entries.append(
                _serialize_node_output(
                    result_id=result_id,
                    node_id=node_id,
                    node_type=node_type,
                    output=output,
                    task_id=task_id,
                    task_duration_ms=task_duration_ms,
                    source_filename=source_filename,
                )
            )
    return entries
