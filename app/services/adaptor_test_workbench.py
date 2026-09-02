from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.adaptor_test import (
    TestCase,
    TestCaseNode,
    TestCaseStatus,
    TestExecution,
    TestExecutionError,
    TestExecutionStatus,
)
from app.models.db.adaptor_test_case_record import (
    AdaptorTestCaseRecord,
    AdaptorTestExecutionRecord,
)
from app.models.execution import NodeOutput
from app.models.workflow import WorkflowDefinition
from app.services.partial_workflow import compute_ancestor_closure

DEFAULT_TTL_SECONDS = 3600


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def _hash_json(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def compute_scope_fingerprint(
    definition: WorkflowDefinition,
    scope_node_ids: set[str],
    input_identities: list[dict[str, object]],
) -> str:
    scoped_nodes = sorted(
        (node.id, node.type, json.dumps(node.config, sort_keys=True))
        for node in definition.nodes
        if node.id in scope_node_ids
    )
    scoped_connections = sorted(
        (connection.source, connection.target, connection.target_port or "")
        for connection in definition.connections
        if connection.source in scope_node_ids and connection.target in scope_node_ids
    )
    return _hash_json(
        {
            "nodes": scoped_nodes,
            "connections": scoped_connections,
            "inputs": sorted(input_identities, key=lambda item: json.dumps(item, sort_keys=True)),
        }
    )


def compute_workflow_fingerprint(definition: WorkflowDefinition) -> str:
    return _hash_json(definition.model_dump(mode="json"))


def _scoped_case_record(
    session: Session,
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> AdaptorTestCaseRecord | None:
    record = session.scalar(
        select(AdaptorTestCaseRecord).where(
            AdaptorTestCaseRecord.id == test_case_id,
            AdaptorTestCaseRecord.workspace_id == workspace_id,
            AdaptorTestCaseRecord.created_by_user_id == user_id,
        )
    )
    if record is None:
        return None
    if record.expires_at <= _utcnow_naive():
        session.execute(
            delete(AdaptorTestExecutionRecord).where(
                AdaptorTestExecutionRecord.test_case_id == test_case_id
            )
        )
        session.delete(record)
        session.commit()
        return None
    return record


def _record_to_test_case(record: AdaptorTestCaseRecord) -> TestCase:
    return TestCase(
        test_case_id=record.id,
        workspace_id=record.workspace_id,
        created_by_user_id=record.created_by_user_id,
        target_node_id=record.target_node_id,
        scope_fingerprint=record.scope_fingerprint,
        workflow_fingerprint=record.workflow_fingerprint,
        status=TestCaseStatus(record.status),
        task_id=record.task_id,
        nodes={
            node_id: TestCaseNode.model_validate(node)
            for node_id, node in record.nodes_json.items()
        },
        input_identities=list(record.input_identities_json),
        created_at=_as_aware(record.created_at),
        expires_at=_as_aware(record.expires_at),
    )


def create_test_case(
    definition: WorkflowDefinition,
    target_node_id: str,
    input_identities: list[dict[str, object]],
    *,
    workspace_id: str,
    user_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> TestCase:
    scope_ids = compute_ancestor_closure(
        definition.nodes,
        definition.connections,
        target_node_id,
        include_target=False,
    )
    if not scope_ids:
        raise ValueError(f"Target node '{target_node_id}' has no ancestor nodes in the workflow")

    now = _utcnow_naive()
    nodes = {
        node.id: TestCaseNode(node_id=node.id, node_type=node.type)
        for node in definition.nodes
        if node.id in scope_ids
    }
    record = AdaptorTestCaseRecord(
        id=f"atc_{uuid4().hex[:16]}",
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        target_node_id=target_node_id,
        scope_fingerprint=compute_scope_fingerprint(definition, scope_ids, input_identities),
        workflow_fingerprint=compute_workflow_fingerprint(definition),
        status=TestCaseStatus.pending.value,
        workflow_json=definition.model_dump(mode="json"),
        nodes_json={node_id: node.model_dump(mode="json") for node_id, node in nodes.items()},
        input_identities_json=input_identities,
        completed_outputs_json={},
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    with SessionLocal() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        return _record_to_test_case(record)


def get_test_case(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> TestCase | None:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return _record_to_test_case(record) if record is not None else None


def get_test_case_definition(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> WorkflowDefinition | None:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record is None:
            return None
        return WorkflowDefinition.model_validate(record.workflow_json)


def set_test_case_status(
    test_case_id: str,
    status: TestCaseStatus,
    *,
    workspace_id: str,
    user_id: str,
) -> TestCase | None:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record is None:
            return None
        record.status = status.value
        session.add(record)
        session.commit()
        session.refresh(record)
        return _record_to_test_case(record)


def update_node_status(
    test_case_id: str,
    node_id: str,
    status: str,
    *,
    workspace_id: str,
    user_id: str,
    output: NodeOutput | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record is None or node_id not in record.nodes_json:
            return
        nodes = dict(record.nodes_json)
        node = TestCaseNode.model_validate(nodes[node_id])
        node.status = status
        node.error = error
        completed_outputs = dict(record.completed_outputs_json)
        if output is not None:
            completed_outputs[node_id] = output.model_dump(mode="json")
            node.output_ref = node_id
        nodes[node_id] = node.model_dump(mode="json")
        record.nodes_json = nodes
        record.completed_outputs_json = completed_outputs
        session.add(record)
        session.commit()


def finalize_test_case(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> TestCase | None:
    test_case = get_test_case(test_case_id, workspace_id=workspace_id, user_id=user_id)
    if test_case is None:
        return None
    all_completed = all(node.status == "completed" for node in test_case.nodes.values())
    any_failed = any(node.status in ("failed", "blocked") for node in test_case.nodes.values())
    if all_completed and test_case.nodes:
        status = TestCaseStatus.ready
    elif any_failed:
        status = TestCaseStatus.blocked
    else:
        status = TestCaseStatus.running_upstream
    return set_test_case_status(
        test_case_id,
        status,
        workspace_id=workspace_id,
        user_id=user_id,
    )


def get_completed_outputs(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> dict[str, NodeOutput]:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record is None:
            return {}
        return {
            node_id: NodeOutput.model_validate(output)
            for node_id, output in record.completed_outputs_json.items()
        }


def get_node_output(
    test_case_id: str,
    node_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> NodeOutput | None:
    return get_completed_outputs(
        test_case_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ).get(node_id)


def delete_test_case(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> bool:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record is None:
            return False
        session.execute(
            delete(AdaptorTestExecutionRecord).where(
                AdaptorTestExecutionRecord.test_case_id == test_case_id
            )
        )
        session.delete(record)
        session.commit()
        return True


def check_staleness(
    test_case_id: str,
    current_definition: WorkflowDefinition,
    current_input_identities: list[dict[str, object]],
    *,
    workspace_id: str,
    user_id: str,
) -> bool:
    test_case = get_test_case(test_case_id, workspace_id=workspace_id, user_id=user_id)
    if test_case is None:
        return False
    return (
        compute_scope_fingerprint(
            current_definition,
            set(test_case.nodes),
            current_input_identities,
        )
        != test_case.scope_fingerprint
    )


def cleanup_expired() -> int:
    now = _utcnow_naive()
    with SessionLocal() as session:
        expired_ids = list(
            session.scalars(
                select(AdaptorTestCaseRecord.id).where(AdaptorTestCaseRecord.expires_at <= now)
            )
        )
        if not expired_ids:
            return 0
        session.execute(
            delete(AdaptorTestExecutionRecord).where(
                AdaptorTestExecutionRecord.test_case_id.in_(expired_ids)
            )
        )
        session.execute(
            delete(AdaptorTestCaseRecord).where(AdaptorTestCaseRecord.id.in_(expired_ids))
        )
        session.commit()
        return len(expired_ids)


def store_execution(
    test_case_id: str,
    code: str,
    input_mode: str,
    bindings: list[dict[str, Any]],
    result: Any,
    *,
    workspace_id: str,
    user_id: str,
) -> str:
    with SessionLocal() as session:
        test_case = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if test_case is None:
            raise ValueError("Test case not found in caller scope")

        status_value = getattr(result, "status", None)
        if status_value is None and isinstance(result, dict):
            status_value = result.get("status")
        status = (
            TestExecutionStatus.succeeded
            if status_value == "succeeded"
            else TestExecutionStatus.failed
        )

        output_value = getattr(result, "output", None)
        if output_value is None and isinstance(result, dict):
            output_value = result.get("output")
        output_payload = (
            output_value.model_dump(mode="json")
            if isinstance(output_value, NodeOutput)
            else output_value
            if isinstance(output_value, dict)
            else None
        )

        error_value = getattr(result, "error", None)
        if error_value is None and isinstance(result, dict):
            error_value = result.get("error")
        error_payload = (
            error_value.model_dump(mode="json")
            if isinstance(error_value, TestExecutionError)
            else error_value
            if isinstance(error_value, dict)
            else None
        )

        now = _utcnow_naive()
        execution_id = f"atexec_{uuid4().hex[:16]}"
        execution = AdaptorTestExecutionRecord(
            id=execution_id,
            test_case_id=test_case_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            status=status.value,
            output_json=output_payload,
            error_json=error_payload,
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
            bindings_json=bindings,
            created_at=now,
            expires_at=test_case.expires_at,
        )
        session.add(execution)
        test_case.last_execution_id = execution_id
        session.add(test_case)
        session.commit()
        return execution_id


def get_execution(
    execution_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    with SessionLocal() as session:
        record = session.scalar(
            select(AdaptorTestExecutionRecord).where(
                AdaptorTestExecutionRecord.id == execution_id,
                AdaptorTestExecutionRecord.workspace_id == workspace_id,
                AdaptorTestExecutionRecord.created_by_user_id == user_id,
                AdaptorTestExecutionRecord.expires_at > _utcnow_naive(),
            )
        )
        if record is None:
            return None
        execution = TestExecution(
            execution_id=record.id,
            test_case_id=record.test_case_id,
            workspace_id=record.workspace_id,
            created_by_user_id=record.created_by_user_id,
            status=TestExecutionStatus(record.status),
            output=record.output_json,
            error=(
                TestExecutionError.model_validate(record.error_json)
                if record.error_json is not None
                else None
            ),
            stdout=record.stdout,
            stderr=record.stderr,
            duration_ms=record.duration_ms,
            code=record.code,
            input_mode=record.input_mode,
            bindings=record.bindings_json,
            created_at=_as_aware(record.created_at),
            expires_at=_as_aware(record.expires_at),
        )
        return {"execution": execution, "test_case_id": record.test_case_id}


def get_last_execution_for_test_case(
    test_case_id: str,
    *,
    workspace_id: str,
    user_id: str,
) -> str | None:
    with SessionLocal() as session:
        record = _scoped_case_record(
            session,
            test_case_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return record.last_execution_id if record is not None else None
