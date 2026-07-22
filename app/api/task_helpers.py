"""Pure utility helpers for the tasks API module.

All functions here are framework-agnostic (no FastAPI route decorators).
They were extracted from ``app.api.tasks`` to keep that file under 800 lines.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import UploadFile
from fastapi.responses import JSONResponse
from typing_extensions import TypedDict

from app.api.constants import ALLOWED_MIME_TYPES
from app.api.error_response import error_response  # noqa: F401 — re-exported for consumers
from app.config import Settings
from app.models.output import OutputMetadata
from app.models.task import TaskContext, TaskInputFile, TaskResult
from app.models.workflow import WorkflowDefinition, WorkflowNode
from app.services.workflow_utils import extract_file_placeholder_index, infer_input_node_type
from app.storage.local import get_storage

logger = logging.getLogger(__name__)

RESULT_PREVIEW_MAX_CHARS = 500
RUNNING_STATUSES = {"pending", "running"}
TERMINAL_TASK_STATUSES = {"completed", "partial_completed", "failed", "cancelled"}


class UploadRecord(TypedDict):
    storage_path: str
    filename: str
    mime_type: str
    size_bytes: int


class FileRecordLike(Protocol):
    @property
    def mime_type(self) -> str: ...


class FileStoreLike(Protocol):
    def get(self, file_id: str) -> FileRecordLike | None: ...


FileStoreGetter = Callable[[], FileStoreLike]


class TaskRunSnapshotLike(Protocol):
    task_id: str
    workflow_id: str | None
    workflow_name: str | None
    run_name: str | None
    status: str | None
    created_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    node_summary: dict[str, int] | None
    result_preview: str | None
    dag_hash: str | None
    input_files: list[dict[str, object]] | None


class ReplayEventLike(Protocol):
    seq: int
    event_type: str
    payload: dict[str, object] | None


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


async def validate_upload(
    file: UploadFile,
    settings: Settings,
) -> bytes | JSONResponse:
    """Validate upload MIME type, emptiness, and size. Returns content bytes or error response."""
    mime_type = (file.content_type or "").lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        return error_response(
            400, "UNSUPPORTED_FILE_TYPE", f"不支援的檔案類型：{mime_type or 'unknown'}"
        )

    content = await file.read()
    if not content:
        return error_response(400, "EMPTY_FILE", "檔案不可為空")

    max_size_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(content) > max_size_bytes:
        return error_response(
            413, "FILE_TOO_LARGE", f"檔案大小超過限制（{settings.max_file_size_mb} MB）"
        )

    return content


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def truncate_result_preview(content: str) -> str:
    return content[:RESULT_PREVIEW_MAX_CHARS]


def parse_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None

    normalized = value.strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def history_sort_key(item: dict[str, object]) -> datetime:
    created_at = parse_datetime_value(item.get("created_at"))
    if created_at is not None:
        return created_at
    return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Upload validation / cleanup
# ---------------------------------------------------------------------------


async def validate_and_store_upload(
    file: UploadFile,
    settings: Settings,
) -> UploadRecord | JSONResponse:
    content = await validate_upload(file, settings)
    if isinstance(content, JSONResponse):
        return content

    mime_type = (file.content_type or "").lower()
    raw_filename = (file.filename or "upload.bin").replace("\\", "/")
    filename = Path(raw_filename).name

    storage = get_storage()
    save_task_id = f"upload_{uuid4()}"
    storage_path = await storage.save_file(save_task_id, "original", filename, content)

    return {
        "storage_path": storage_path,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(content),
    }


async def cleanup_uploaded_files(
    uploaded_files: list[UploadRecord],
    settings: Settings,
) -> None:
    if not uploaded_files:
        return

    storage = get_storage()
    for uploaded in uploaded_files:
        file_path = uploaded.get("storage_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        try:
            await storage.delete_file(file_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to cleanup uploaded file error_type=%s",
                type(exc).__name__,
            )


# ---------------------------------------------------------------------------
# Workflow input bindings
# ---------------------------------------------------------------------------


def build_workflow_input_bindings(
    definition: WorkflowDefinition,
    uploaded_files: list[UploadRecord],
) -> dict[str, TaskInputFile]:
    input_nodes = [node for node in definition.nodes if node.type.startswith("input/")]
    if not input_nodes:
        raise ValueError("Workflow 缺少 input 節點")

    placeholder_indexes: dict[str, int] = {}
    required_files = len(input_nodes)
    for node in input_nodes:
        placeholder_index = extract_file_placeholder_index(node.config.get("file"))
        if placeholder_index is None:
            continue
        placeholder_indexes[node.id] = placeholder_index
        required_files = max(required_files, placeholder_index + 1)

    if len(uploaded_files) < required_files:
        input_node_ids = ", ".join(node.id for node in input_nodes)
        raise ValueError(
            f"files 數量不足：Workflow 有 {len(input_nodes)} 個 input 節點（{input_node_ids}），"
            f"需要至少 {required_files} 個 files，實際 {len(uploaded_files)} 個"
        )

    bindings: dict[str, TaskInputFile] = {}
    for index, node in enumerate(input_nodes):
        upload_index = placeholder_indexes.get(node.id, index)
        uploaded = uploaded_files[upload_index]
        bindings[node.id] = TaskInputFile(
            file_path=uploaded["storage_path"],
            filename=uploaded["filename"],
            mime_type=uploaded["mime_type"],
            size_bytes=uploaded["size_bytes"],
        )

    return bindings


# ---------------------------------------------------------------------------
# Node-run helpers
# ---------------------------------------------------------------------------


def resolve_node_run_file_index(input_node: WorkflowNode | None, file_count: int) -> int:
    if file_count <= 0:
        raise ValueError("node-run 需要至少一個輸入檔案")
    if input_node is None:
        return 0

    placeholder_index = extract_file_placeholder_index(input_node.config.get("file"))
    if placeholder_index is None:
        return 0
    if placeholder_index >= file_count:
        raise ValueError(
            "node-run files 數量不足："
            f"需要至少 {placeholder_index + 1} 個 files，實際 {file_count} 個"
        )
    return placeholder_index


def find_upstream_input_node(definition: WorkflowDefinition, node_id: str) -> WorkflowNode | None:
    nodes_by_id = {node.id: node for node in definition.nodes}
    visited = {node_id}
    queue = [node_id]

    while queue:
        current = queue.pop(0)
        predecessors = [conn.source for conn in definition.connections if conn.target == current]
        for predecessor_id in predecessors:
            if predecessor_id in visited:
                continue
            visited.add(predecessor_id)
            predecessor = nodes_by_id.get(predecessor_id)
            if predecessor is None:
                continue
            if predecessor.type.startswith("input/"):
                return predecessor
            queue.append(predecessor_id)

    for node in definition.nodes:
        if node.type.startswith("input/"):
            return node
    return None


def resolve_node_run_input_type(
    *,
    input_node: WorkflowNode | None,
    upload_record: UploadRecord | None,
    file_id: str | None,
    file_store_getter: FileStoreGetter | None = None,
) -> str:
    if input_node is not None and input_node.type.startswith("input/"):
        return input_node.type

    mime_type: str | None = None
    if upload_record is not None:
        mime_type = upload_record["mime_type"]
    elif file_id is not None:
        if file_store_getter is None:
            from app.api.files import get_file_store

            file_store_getter = get_file_store
        store = file_store_getter()
        record = store.get(file_id)
        if record is None:
            raise ValueError(f"找不到檔案：{file_id}")
        mime_type = record.mime_type

    if mime_type is None:
        raise ValueError("無法推斷 node-run input 類型")

    return infer_input_node_type(mime_type)


# ---------------------------------------------------------------------------
# Context / snapshot status helpers
# ---------------------------------------------------------------------------


def extract_context_status(context: TaskContext | None) -> str | None:
    if context is None:
        return None

    status_value = context.status.value
    if status_value:
        return status_value
    return None


async def resolve_status_from_snapshot_if_terminal(
    repository: object,
    task_id: str,
    runtime_status: str | None,
) -> tuple[str | None, object | None]:
    if runtime_status not in RUNNING_STATUSES:
        return runtime_status, None

    get_snapshot = getattr(repository, "get_snapshot", None)
    if not callable(get_snapshot):
        return runtime_status, None

    snapshot_value = get_snapshot(task_id)
    if inspect.isawaitable(snapshot_value):
        snapshot_value = await snapshot_value

    snapshot_status = getattr(snapshot_value, "status", None)
    if isinstance(snapshot_status, str) and snapshot_status in TERMINAL_TASK_STATUSES:
        return snapshot_status, snapshot_value

    return runtime_status, snapshot_value


def is_results_ready_status(status: str | None) -> bool:
    return status in {"completed", "partial_completed"}


def task_state_unavailable_response(task_id: str) -> JSONResponse:
    return error_response(
        503,
        "TASK_STATE_UNAVAILABLE",
        f"任務狀態暫時不可用，請稍後重試：{task_id}",
    )


# ---------------------------------------------------------------------------
# Result collection / restoration
# ---------------------------------------------------------------------------


def collect_results_from_context(
    task_id: str,
    result: TaskResult | None,
    node_states: Mapping[str, object],
) -> list[TaskResult]:
    results: list[TaskResult] = []
    if result is not None:
        results.append(result)

    for state in node_states.values():
        output = getattr(state, "output", None)
        if isinstance(output, TaskResult) and all(
            item.result_id != output.result_id for item in results
        ):
            results.append(output)

    # Ensure deterministic ordering for API consumers.
    return sorted(results, key=lambda item: item.result_id)


def extract_final_output_from_context(context: TaskContext) -> tuple[str, str]:
    return context.extract_final_output()


def collect_results_from_snapshot(
    task_id: str,
    snapshot_results: Sequence[Mapping[str, object]],
) -> list[TaskResult]:
    results: list[TaskResult] = []
    for item in snapshot_results:
        restored = restore_task_result_from_snapshot_item(task_id, item)
        if restored is None:
            continue
        if all(existing.result_id != restored.result_id for existing in results):
            results.append(restored)
    return sorted(results, key=lambda item: item.result_id)


def restore_task_result_from_snapshot_item(
    task_id: str,
    item: Mapping[str, object],
) -> TaskResult | None:
    result_id = item.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        return None

    file_info = item.get("file")
    file_dict = file_info if isinstance(file_info, Mapping) else {}

    storage_path = file_dict.get("storage_path", item.get("storage_path"))
    filename = file_dict.get("filename", item.get("filename"))
    content_type = file_dict.get("content_type", item.get("content_type"))
    if not isinstance(storage_path, str) or not storage_path:
        return None
    if not isinstance(filename, str) or not filename:
        return None
    if not isinstance(content_type, str) or not content_type:
        return None

    output_format = item.get("output_format")
    if not isinstance(output_format, str) or not output_format:
        output_format = "markdown"

    content = item.get("content")
    if not isinstance(content, str):
        content = ""

    download_url = file_dict.get("download_url", item.get("download_url"))
    if not isinstance(download_url, str) or not download_url:
        download_url = f"/api/tasks/{task_id}/results/{result_id}/download"

    metadata_payload = item.get("metadata")
    metadata_dict = metadata_payload if isinstance(metadata_payload, dict) else {}

    def _as_int(value: object, default: int = 0) -> int:
        return value if isinstance(value, int) else default

    metadata = OutputMetadata(
        processing_time_ms=max(_as_int(metadata_dict.get("processing_time_ms")), 0),
        page_count=max(_as_int(metadata_dict.get("page_count"), 1), 1),
        char_count=max(_as_int(metadata_dict.get("char_count"), len(content)), 0),
        word_count=max(_as_int(metadata_dict.get("word_count"), len(content.split())), 0),
        source_filename=filename,
    )

    return TaskResult(
        result_id=result_id,
        format=output_format,
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        download_url=download_url,
        content=content,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Result entry building / normalization
# ---------------------------------------------------------------------------


def build_result_entries_from_context(context: object) -> list[dict[str, object]]:

    workflow = getattr(context, "workflow", None)
    node_states = getattr(context, "node_states", {})
    fallback_engine = str(getattr(context, "engine", "ocr"))
    fallback_duration = getattr(context, "duration_ms", None)
    fallback_duration_ms = fallback_duration if isinstance(fallback_duration, int) else 0

    entries: list[dict[str, object]] = []
    seen_result_ids: set[str] = set()

    if isinstance(workflow, WorkflowDefinition) and isinstance(node_states, dict):
        # Derive results from nodes connected to end node
        end_node = next((n for n in workflow.nodes if n.type == "end/final"), None)
        upstream_of_end: list[str] = []
        if end_node is not None:
            upstream_of_end = [c.source for c in workflow.connections if c.target == end_node.id]

        for upstream_id in upstream_of_end:
            state = node_states.get(upstream_id)
            output = getattr(state, "output", None)
            if not isinstance(output, TaskResult):
                continue
            if output.result_id in seen_result_ids:
                continue
            seen_result_ids.add(output.result_id)

            # Infer engine type from node type
            upstream_node = next((n for n in workflow.nodes if n.id == upstream_id), None)
            engine_type = (
                upstream_node.type.split("/", 1)[1]
                if upstream_node and upstream_node.type.startswith("engine/")
                else fallback_engine or "unknown"
            )
            output_format = engine_type
            duration_ms = output.metadata.processing_time_ms
            if duration_ms <= 0:
                duration_ms = fallback_duration_ms

            entries.append(
                {
                    "result_id": output.result_id,
                    "node_id": upstream_id,
                    "node_type": f"engine/{engine_type}",
                    "engine_type": engine_type,
                    "output_format": output_format,
                    "result_preview": truncate_result_preview(output.content),
                    "duration_ms": duration_ms,
                    "status": "completed",
                    "file": {
                        "filename": output.filename,
                        "size_bytes": len(output.content.encode("utf-8")),
                        "content_type": output.content_type,
                        "storage_path": output.storage_path,
                        "download_url": output.download_url,
                    },
                    "metadata": {
                        "processing_time_ms": output.metadata.processing_time_ms,
                        "page_count": output.metadata.page_count,
                        "char_count": output.metadata.char_count,
                        "word_count": output.metadata.word_count,
                    },
                    "content": output.content,
                }
            )

    if not entries:
        task_id = str(getattr(context, "task_id", ""))
        fallback_models = collect_results_from_context(
            task_id,
            getattr(context, "result", None),
            node_states,
        )
        for fallback in fallback_models:
            duration_ms = fallback.metadata.processing_time_ms
            if duration_ms <= 0:
                duration_ms = fallback_duration_ms
            entries.append(
                {
                    "result_id": fallback.result_id,
                    "node_id": "engine_1",
                    "node_type": f"engine/{fallback_engine}",
                    "engine_type": fallback_engine,
                    "output_format": fallback.format,
                    "result_preview": truncate_result_preview(fallback.content),
                    "duration_ms": duration_ms,
                    "status": "completed",
                    "file": {
                        "filename": fallback.filename,
                        "size_bytes": len(fallback.content.encode("utf-8")),
                        "content_type": fallback.content_type,
                        "storage_path": fallback.storage_path,
                        "download_url": fallback.download_url,
                    },
                    "metadata": {
                        "processing_time_ms": fallback.metadata.processing_time_ms,
                        "page_count": fallback.metadata.page_count,
                        "char_count": fallback.metadata.char_count,
                        "word_count": fallback.metadata.word_count,
                    },
                    "content": fallback.content,
                }
            )

    entries.sort(key=lambda item: str(item.get("result_id", "")))
    return entries


def ensure_result_fields(
    item: dict[str, object],
    *,
    fallback_duration_ms: int | None = None,
) -> dict[str, object]:
    result = dict(item)
    content = str(result.get("content", ""))

    node_type_value = str(result.get("node_type", ""))
    if node_type_value.startswith("engine/"):
        inferred_engine = node_type_value.split("/", 1)[1]
    else:
        inferred_engine = "ocr"

    engine_type = result.get("engine_type")
    if not isinstance(engine_type, str) or not engine_type:
        engine_type = inferred_engine
    result["engine_type"] = engine_type

    output_format = result.get("output_format")
    if not isinstance(output_format, str) or not output_format:
        output_format = "markdown"
    result["output_format"] = output_format

    status_value = result.get("status")
    if not isinstance(status_value, str) or not status_value:
        status_value = "completed"
    result["status"] = status_value

    result_preview = result.get("result_preview")
    if not isinstance(result_preview, str):
        result_preview = truncate_result_preview(content)
    result["result_preview"] = truncate_result_preview(result_preview)

    duration_ms = result.get("duration_ms")
    if not isinstance(duration_ms, int):
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("processing_time_ms"), int):
            duration_ms = int(metadata["processing_time_ms"])
        elif isinstance(fallback_duration_ms, int):
            duration_ms = fallback_duration_ms
        else:
            duration_ms = 0
    result["duration_ms"] = max(duration_ms, 0)

    return result


def build_results_response(
    *,
    task_id: str,
    status: str,
    results: list[dict[str, object]],
) -> JSONResponse:
    completed_count = sum(1 for item in results if item.get("status") == "completed")
    failed_count = len(results) - completed_count
    return JSONResponse(
        status_code=200,
        content={
            "task_id": task_id,
            "status": status,
            "results": results,
            "summary": {
                "total_outputs": len(results),
                "completed": completed_count,
                "failed": failed_count,
            },
        },
    )


# ---------------------------------------------------------------------------
# SSE event payload builders
# ---------------------------------------------------------------------------


def task_completed_event_payload(context: TaskContext) -> dict[str, object]:
    started_at = context.started_at.isoformat() if context.started_at else None
    completed_at = (
        context.completed_at.isoformat()
        if context.completed_at
        else datetime.now(timezone.utc).isoformat()
    )
    duration_seconds = 0
    if context.started_at and context.completed_at:
        duration_seconds = max(int((context.completed_at - context.started_at).total_seconds()), 0)

    # Collect states for nodes connected to end node
    end_node = next((n for n in context.workflow.nodes if n.type == "end/final"), None)
    upstream_ids: set[str] = set()
    if end_node is not None:
        upstream_ids = {c.source for c in context.workflow.connections if c.target == end_node.id}
    output_states = [
        state for state in context.node_states.values() if state.node_id in upstream_ids
    ]
    output_totals = {
        "total": len(output_states),
        "completed": sum(1 for state in output_states if state.status.value == "completed"),
        "failed_or_skipped": sum(
            1 for state in output_states if state.status.value in {"failed", "skipped"}
        ),
    }

    summary: dict[str, object] = {
        "total_nodes": context.progress.total_nodes,
        "completed": context.progress.completed_nodes,
        "failed": context.progress.failed_nodes,
        "skipped": context.progress.skipped_nodes,
        "output_totals": output_totals,
    }
    if context.end_summary is not None:
        summary["end_node"] = context.end_summary

    return {
        "task_id": context.task_id,
        "status": context.status.value,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "summary": summary,
    }


def task_failed_event_payload(context: TaskContext) -> dict[str, object]:
    failed_at = (
        context.completed_at.isoformat()
        if context.completed_at
        else datetime.now(timezone.utc).isoformat()
    )
    return {
        "task_id": context.task_id,
        "status": context.status.value,
        "error": context.error or "Task execution failed",
        "failed_at": failed_at,
    }


# ---------------------------------------------------------------------------
# Snapshot / history helpers
# ---------------------------------------------------------------------------


def history_entry_from_snapshot(snapshot: TaskRunSnapshotLike) -> dict[str, object] | None:
    if snapshot.status is None:
        return None

    return {
        "task_id": snapshot.task_id,
        "workflow_id": snapshot.workflow_id,
        "workflow_name": snapshot.workflow_name,
        "run_name": snapshot.run_name,
        "status": snapshot.status,
        "started_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "completed_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
        "duration_ms": snapshot.duration_ms,
        "node_summary": snapshot.node_summary or {},
        "result_preview": (
            truncate_result_preview(snapshot.result_preview)
            if isinstance(snapshot.result_preview, str)
            else None
        ),
        "dag_hash": getattr(snapshot, "dag_hash", None),
        "input_files": getattr(snapshot, "input_files", None),
    }


def serialize_replay_event(event_log: ReplayEventLike) -> dict[str, object]:
    payload = event_log.payload if isinstance(event_log.payload, dict) else {}
    return {
        "seq": event_log.seq,
        "event": event_log.event_type,
        "data": payload,
    }


async def call_repository_method(
    repository: object,
    method_names: tuple[str, ...],
    *args: object,
) -> object:
    for method_name in method_names:
        method = getattr(repository, method_name, None)
        if method is None:
            continue

        try:
            value = method(*args)
        except TypeError:
            continue

        if inspect.isawaitable(value):
            return await value
        return value
    return None


async def load_persisted_results_payload(
    repository: object,
    task_id: str,
) -> tuple[str | None, int | None, list[dict[str, object]] | None, bool]:
    from app.repositories.task_run_repository import TaskRunSnapshot

    get_snapshot = getattr(repository, "get_snapshot", None)
    if callable(get_snapshot):
        snapshot_value = get_snapshot(task_id)
        if inspect.isawaitable(snapshot_value):
            snapshot_value = await snapshot_value

        if isinstance(snapshot_value, TaskRunSnapshot):
            normalized_results = (
                snapshot_value.results if isinstance(snapshot_value.results, list) else []
            )
            return snapshot_value.status, snapshot_value.duration_ms, normalized_results, True
        if snapshot_value is not None and hasattr(snapshot_value, "results"):
            status_value = getattr(snapshot_value, "status", None)
            duration_value = getattr(snapshot_value, "duration_ms", None)
            results_value = getattr(snapshot_value, "results", None)
            normalized_status = status_value if isinstance(status_value, str) else None
            normalized_duration = duration_value if isinstance(duration_value, int) else None
            normalized_results = results_value if isinstance(results_value, list) else []
            return normalized_status, normalized_duration, normalized_results, True

    status_value = await call_repository_method(
        repository,
        ("get_task_status", "task_status", "status_for_task"),
        task_id,
    )
    results_value = await call_repository_method(
        repository,
        (
            "get_task_results",
            "list_results",
            "fetch_results",
            "list_task_results",
            "results_for_task",
        ),
        task_id,
    )

    if not isinstance(results_value, list):
        exists_value = await call_repository_method(
            repository,
            ("task_exists", "exists", "has_task"),
            task_id,
        )
        if not bool(exists_value):
            return None, None, None, False
        results_value = []

    normalized_results = [item for item in results_value if isinstance(item, dict)]
    if not normalized_results and not isinstance(status_value, str):
        exists_value = await call_repository_method(
            repository,
            ("task_exists", "exists", "has_task"),
            task_id,
        )
        if not bool(exists_value):
            return None, None, None, False

    status = str(status_value) if isinstance(status_value, str) else None
    return status, None, normalized_results, True


def resolve_preview_from_context(context: TaskContext | None) -> str | None:
    if context is None:
        return None

    entries = build_result_entries_from_context(context)
    if entries:
        preview = entries[0].get("result_preview")
        if isinstance(preview, str):
            return truncate_result_preview(preview)

    result = getattr(context, "result", None)
    if isinstance(result, TaskResult):
        return truncate_result_preview(result.content)

    return None
