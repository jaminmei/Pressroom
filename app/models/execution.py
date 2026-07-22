from __future__ import annotations

from pydantic import BaseModel, Field


class BinaryRef(BaseModel):
    ref: str = ""
    data: str | None = None
    mime_type: str = ""
    size_bytes: int = 0
    dimensions: dict | None = None


class NodeOutput(BaseModel):
    text: str | None = None
    binary: list[BinaryRef] = Field(default_factory=list)
    structured: dict | None = None
    metadata: dict = Field(default_factory=dict)


class ResolvedInput(BaseModel):
    name: str
    source_node_id: str
    source_event_id: str
    port_index: int | None = None


class ErrorInfo(BaseModel):
    type: str
    message: str
    retry_count: int = 0
    is_retryable: bool = False


class ExecutionEvent(BaseModel):
    event_id: str
    workflow_run_id: str
    node_id: str
    node_type: str
    event_type: str
    sequence: int
    timestamp: float
    output: NodeOutput | None = None
    resolved_inputs: dict[str, ResolvedInput] = Field(default_factory=dict)
    error: ErrorInfo | None = None
