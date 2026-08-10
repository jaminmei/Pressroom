from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

from app.models.adaptor_test import TestCase, TestCaseNode, TestCaseStatus
from app.models.execution import NodeOutput
from app.models.workflow import WorkflowDefinition
from app.services.partial_workflow import compute_ancestor_closure

_TEST_CASES: dict[str, dict[str, Any]] = {}
_TEST_EXECUTIONS: dict[str, dict[str, Any]] = {}

DEFAULT_TTL_SECONDS = 3600


def _hash_json(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def compute_scope_fingerprint(
    definition: WorkflowDefinition, scope_node_ids: set[str], input_identities: list[dict]
) -> str:
    scoped_nodes = sorted(
        (n.id, n.type, json.dumps(n.config, sort_keys=True))
        for n in definition.nodes
        if n.id in scope_node_ids
    )
    scoped_connections = sorted(
        (c.source, c.target, c.target_port or "")
        for c in definition.connections
        if c.source in scope_node_ids and c.target in scope_node_ids
    )
    return _hash_json(
        {
            "nodes": scoped_nodes,
            "connections": scoped_connections,
            "inputs": sorted(input_identities, key=lambda x: json.dumps(x, sort_keys=True)),
        }
    )


def compute_workflow_fingerprint(definition: WorkflowDefinition) -> str:
    return _hash_json(definition.model_dump(mode="json"))


def create_test_case(
    definition: WorkflowDefinition,
    target_node_id: str,
    input_identities: list[dict],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> TestCase:
    scope_ids = compute_ancestor_closure(
        definition.nodes, definition.connections, target_node_id, include_target=False
    )

    if not scope_ids:
        raise ValueError(f"Target node '{target_node_id}' has no ancestor nodes in the workflow")

    scope_fp = compute_scope_fingerprint(definition, scope_ids, input_identities)
    workflow_fp = compute_workflow_fingerprint(definition)

    test_case_id = f"atc_{uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)

    nodes: dict[str, TestCaseNode] = {}
    for node in definition.nodes:
        if node.id in scope_ids:
            nodes[node.id] = TestCaseNode(
                node_id=node.id,
                node_type=node.type,
                status="pending",
            )

    test_case = TestCase(
        test_case_id=test_case_id,
        target_node_id=target_node_id,
        scope_fingerprint=scope_fp,
        workflow_fingerprint=workflow_fp,
        status=TestCaseStatus.pending,
        nodes=nodes,
        input_identities=input_identities,
        created_at=now,
        expires_at=expires_at,
    )

    _TEST_CASES[test_case_id] = {
        "test_case": test_case,
        "definition": definition,
        "completed_outputs": {},
    }

    return test_case


def get_test_case(test_case_id: str) -> TestCase | None:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return None
    test_case: TestCase = entry["test_case"]
    if test_case.expires_at and datetime.now(timezone.utc) > test_case.expires_at:
        _TEST_CASES.pop(test_case_id, None)
        return None
    return test_case


def get_test_case_definition(test_case_id: str) -> WorkflowDefinition | None:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return None
    definition = entry.get("definition")
    return definition if isinstance(definition, WorkflowDefinition) else None


def update_node_status(
    test_case_id: str,
    node_id: str,
    status: str,
    output: NodeOutput | None = None,
    error: dict | None = None,
) -> None:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return
    test_case: TestCase = entry["test_case"]
    if node_id in test_case.nodes:
        test_case.nodes[node_id].status = status
        test_case.nodes[node_id].error = error
        if output is not None:
            entry["completed_outputs"][node_id] = output
            test_case.nodes[node_id].output_ref = node_id


def finalize_test_case(test_case_id: str) -> TestCase | None:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return None
    test_case: TestCase = entry["test_case"]
    all_completed = all(n.status == "completed" for n in test_case.nodes.values())
    any_failed = any(n.status in ("failed", "blocked") for n in test_case.nodes.values())
    if all_completed and test_case.nodes:
        test_case.status = TestCaseStatus.ready
    elif any_failed:
        test_case.status = TestCaseStatus.blocked
    else:
        test_case.status = TestCaseStatus.running_upstream
    return test_case


def get_completed_outputs(test_case_id: str) -> dict[str, NodeOutput]:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return {}
    return cast(dict[str, NodeOutput], entry.get("completed_outputs", {}))


def get_node_output(test_case_id: str, node_id: str) -> NodeOutput | None:
    return get_completed_outputs(test_case_id).get(node_id)


def delete_test_case(test_case_id: str) -> bool:
    return _TEST_CASES.pop(test_case_id, None) is not None


def check_staleness(
    test_case_id: str,
    current_definition: WorkflowDefinition,
    current_input_identities: list[dict],
) -> bool:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return False
    test_case: TestCase = entry["test_case"]
    scope_ids = set(test_case.nodes.keys())
    current_scope_fp = compute_scope_fingerprint(
        current_definition,
        scope_ids,
        current_input_identities,
    )
    return current_scope_fp != test_case.scope_fingerprint


def cleanup_expired() -> int:
    now = datetime.now(timezone.utc)
    expired = [
        tc_id
        for tc_id, entry in _TEST_CASES.items()
        if entry["test_case"].expires_at and now > entry["test_case"].expires_at
    ]
    for tc_id in expired:
        _TEST_CASES.pop(tc_id, None)
    return len(expired)


def store_execution(
    test_case_id: str,
    code: str,
    input_mode: str,
    bindings: list[dict],
    result: Any,
) -> str:
    from app.models.adaptor_test import TestExecution, TestExecutionError, TestExecutionStatus

    execution_id = f"atexec_{uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)

    status_value = getattr(result, "status", None)
    if status_value is None and isinstance(result, dict):
        status_value = result.get("status")
    if status_value == "succeeded":
        status = TestExecutionStatus.succeeded
    else:
        status = TestExecutionStatus.failed

    output_value = getattr(result, "output", None)
    if output_value is None and isinstance(result, dict):
        output_value = result.get("output")
    if isinstance(output_value, NodeOutput):
        output_payload = output_value.model_dump(mode="json")
    elif isinstance(output_value, dict):
        output_payload = output_value
    else:
        output_payload = None

    error_value = getattr(result, "error", None)
    if error_value is None and isinstance(result, dict):
        error_value = result.get("error")
    if isinstance(error_value, TestExecutionError):
        error_payload = error_value
    elif isinstance(error_value, dict):
        error_payload = TestExecutionError.model_validate(error_value)
    else:
        error_payload = None

    exec_model = TestExecution(
        execution_id=execution_id,
        test_case_id=test_case_id,
        status=status,
        output=output_payload,
        error=error_payload,
        stdout=str(
            getattr(result, "stdout", "")
            if not isinstance(result, dict)
            else result.get("stdout", "")
        ),
        stderr=str(
            getattr(result, "stderr", "")
            if not isinstance(result, dict)
            else result.get("stderr", "")
        ),
        duration_ms=int(
            getattr(result, "duration_ms", 0)
            if not isinstance(result, dict)
            else result.get("duration_ms", 0) or 0
        ),
        code=code,
        input_mode=input_mode,
        bindings=bindings,
        created_at=now,
    )

    _TEST_EXECUTIONS[execution_id] = {
        "execution": exec_model,
        "test_case_id": test_case_id,
    }

    entry = _TEST_CASES.get(test_case_id)
    if entry is not None:
        entry["last_execution_id"] = execution_id

    return execution_id


def get_execution(execution_id: str) -> dict[str, Any] | None:
    return _TEST_EXECUTIONS.get(execution_id)


def get_last_execution_for_test_case(test_case_id: str) -> str | None:
    entry = _TEST_CASES.get(test_case_id)
    if entry is None:
        return None
    return entry.get("last_execution_id")
