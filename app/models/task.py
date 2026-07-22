from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from app.models.output import OutputMetadata
from app.models.workflow import WorkflowDefinition


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_COMPLETED = "partial_completed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_USER_INPUT = "awaiting_user_input"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskProgress(BaseModel):
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    pending_nodes: int = 0
    skipped_nodes: int = 0
    current_node: str | None = None
    percentage: int = 0


class TaskResult(BaseModel):
    result_id: str
    format: str
    filename: str
    content_type: str
    storage_path: str
    download_url: str
    content: str
    metadata: OutputMetadata


class NodeFailureInfo(TypedDict, total=False):
    error_code: str
    message: str
    details: dict[str, Any]


def build_node_failure_info(
    *,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> NodeFailureInfo:
    failure: NodeFailureInfo = {
        "error_code": error_code,
        "message": message,
    }
    if details:
        failure["details"] = details
    return failure


def node_failure_message(error: NodeFailureInfo | str | None) -> str | None:
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(error, str) and error:
        return error
    return None


def node_failure_summary(
    error: NodeFailureInfo | str | None,
    *,
    default_error_code: str,
    default_message: str,
) -> dict[str, str]:
    if isinstance(error, dict):
        error_code = error.get("error_code")
        message = error.get("message")
        return {
            "error_code": (
                error_code if isinstance(error_code, str) and error_code else default_error_code
            ),
            "message": message if isinstance(message, str) and message else default_message,
        }
    if isinstance(error, str) and error:
        return {
            "error_code": default_error_code,
            "message": error,
        }
    return {
        "error_code": default_error_code,
        "message": default_message,
    }


class NodeState(BaseModel):
    node_id: str
    node_type: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: object | None = None
    error: NodeFailureInfo | str | None = None
    progress: dict[str, object] | None = None


class TaskInputFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_id: str | None = None
    file_path: str
    filename: str
    mime_type: str
    size_bytes: int | None = None
    workspace_id: str | None = None
    uploaded_by_user_id: str | None = None


class WorkflowExecutionPlan(BaseModel):
    total_nodes: int
    execution_order: list[list[str]]
    parallel_groups: int
    estimated_duration_seconds: int | None = None


class TaskContext(BaseModel):
    task_id: str
    workflow: WorkflowDefinition
    workflow_id: str | None = None
    workspace_id: str | None = None
    requested_by_user_id: str | None = None
    workflow_name: str | None = None
    run_name: str | None = None  # User-defined run name for identification
    source: str = "manual"
    evaluation_run_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    node_states: dict[str, NodeState] = Field(default_factory=dict)
    execution_plan: WorkflowExecutionPlan
    input_files: dict[str, TaskInputFile] = Field(default_factory=dict)
    output_result_ids: dict[str, str] = Field(default_factory=dict)
    end_summary: dict[str, object] | None = None

    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None

    progress: TaskProgress = Field(default_factory=TaskProgress)

    # Legacy-compatible fields for existing API consumers.
    source_file_path: str | None = None
    source_filename: str | None = None
    source_mime_type: str | None = None
    output_format: str = "markdown"
    engine: str = "ocr"
    result: TaskResult | None = None
    error: str | None = None

    cancel_requested: bool = False

    def iter_results(self) -> list[TaskResult]:
        results: list[TaskResult] = []
        if self.result is not None:
            results.append(self.result)

        for state in self.node_states.values():
            if isinstance(state.output, TaskResult) and all(
                item.result_id != state.output.result_id for item in results
            ):
                results.append(state.output)

        return sorted(results, key=lambda item: item.result_id)

    def extract_final_output(self) -> tuple[str, str]:
        results_by_id = {item.result_id: item for item in self.iter_results()}

        for result_id in self.output_result_ids.values():
            result = results_by_id.get(result_id)
            if result is not None:
                return result.content, result.format

        raise ValueError("No output result found")

    def refresh_progress(self) -> None:
        completed = sum(
            1 for node in self.node_states.values() if node.status == NodeStatus.COMPLETED
        )
        failed = sum(1 for node in self.node_states.values() if node.status == NodeStatus.FAILED)
        skipped = sum(1 for node in self.node_states.values() if node.status == NodeStatus.SKIPPED)
        pending = sum(1 for node in self.node_states.values() if node.status == NodeStatus.PENDING)
        running_node = next(
            (
                node.node_id
                for node in self.node_states.values()
                if node.status == NodeStatus.RUNNING
            ),
            None,
        )

        total = len(self.node_states)
        percentage = int((completed / total) * 100) if total else 0

        self.progress = TaskProgress(
            total_nodes=total,
            completed_nodes=completed,
            failed_nodes=failed,
            pending_nodes=pending,
            skipped_nodes=skipped,
            current_node=running_node,
            percentage=percentage,
        )


class TaskHistorySummary(BaseModel):
    task_id: str
    workflow_id: str | None = None
    workspace_id: str | None = None
    workflow_name: str | None = None
    run_name: str | None = None  # User-defined run name
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    node_summary: dict[str, int] = Field(default_factory=dict)
