from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TestCaseStatus(str, Enum):
    pending = "pending"
    running_upstream = "running_upstream"
    ready = "ready"
    blocked = "blocked"
    failed = "failed"
    stale = "stale"


class TestCaseNode(BaseModel):
    node_id: str
    node_type: str
    status: str = "pending"
    error: dict[str, Any] | None = None
    output_ref: str | None = None


class TestCase(BaseModel):
    test_case_id: str
    target_node_id: str
    scope_fingerprint: str
    workflow_fingerprint: str
    status: TestCaseStatus = TestCaseStatus.pending
    task_id: str | None = None
    nodes: dict[str, TestCaseNode] = Field(default_factory=dict)
    input_identities: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None


class TestExecutionStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class TestExecutionErrorPhase(str, Enum):
    binding_resolution = "binding_resolution"
    compile = "compile"
    runtime = "runtime"
    timeout = "timeout"
    output_validation = "output_validation"
    sandbox_transport = "sandbox_transport"
    upstream_validation = "upstream_validation"
    upstream_execution = "upstream_execution"


class TestExecutionError(BaseModel):
    phase: TestExecutionErrorPhase
    type: str | None = None
    message: str
    traceback: str | None = None
    line: int | None = None
    column: int | None = None
    retryable: bool = False


class TestExecution(BaseModel):
    execution_id: str
    test_case_id: str
    status: TestExecutionStatus = TestExecutionStatus.pending
    output: dict[str, Any] | None = None
    error: TestExecutionError | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    code: str = ""
    input_mode: str = "all_upstream"
    bindings: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
