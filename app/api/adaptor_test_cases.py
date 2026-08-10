from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from typing_extensions import TypedDict

from app.api.auth import require_workspace_capability
from app.api.error_response import error_response
from app.api.task_helpers import UploadRecord, cleanup_uploaded_files, validate_and_store_upload
from app.config import get_settings
from app.models.adaptor_test import TestCaseStatus
from app.models.execution import NodeOutput
from app.models.task import TaskInputFile
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.adaptor_bindings import BindingResolutionError
from app.services.adaptor_executor import (
    _inline_storage_root_binary_refs,
    assert_adaptor_sandbox_ready,
    validate_adaptor_sandbox_broker_url,
)
from app.services.adaptor_resolver import resolve_adaptor_inputs
from app.services.adaptor_test_workbench import (
    create_test_case,
    delete_test_case,
    finalize_test_case,
    get_completed_outputs,
    get_execution,
    get_node_output,
    get_test_case,
    get_test_case_definition,
    store_execution,
    update_node_status,
)
from app.services.engine_client import make_node_executor
from app.services.partial_workflow import compute_ancestor_closure
from app.services.sandbox_client import SandboxClient
from app.services.workspace_access import ResolvedContext
from sandbox_protocol.models import SandboxLimits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["adaptor-test-cases"])

UploadFilesParam = Annotated[list[UploadFile] | None, File()]
ExecutionBodyParam = Annotated[dict[str, Any], Body()]


class ExecutionResultPayload(TypedDict):
    status: str
    output: dict[str, Any] | NodeOutput | None
    error: dict[str, Any] | None
    stdout: str
    stderr: str
    duration_ms: int


WorkflowRunContext = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("workflow.run")),
]


def _provider_resolver_for_request(
    request: Request,
    workspace_id: str | None,
) -> Any:
    provider_resolver = getattr(request.app.state, "provider_resolver", None)
    if provider_resolver is not None:
        return provider_resolver

    provider_store = getattr(request.app.state, "provider_store", None)
    if provider_store is None or workspace_id is None:
        return None

    return lambda provider_id: provider_store.get_for_runtime(provider_id, workspace_id)


def _input_identities_from_request(
    uploads: list[UploadFile] | None,
    file_ids: str | None,
) -> list[dict[str, object]]:
    identities: list[dict[str, object]] = []
    if uploads:
        for upload in uploads:
            identities.append(
                {
                    "filename": upload.filename,
                    "content_type": upload.content_type,
                }
            )
    if file_ids:
        try:
            parsed = json.loads(file_ids)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            identities.extend(
                {"file_id": file_id} for file_id in parsed if isinstance(file_id, str)
            )
    return identities


def _test_case_response_payload(test_case_id: str) -> JSONResponse:
    test_case = get_test_case(test_case_id)
    if test_case is None:
        return error_response(404, "TEST_CASE_NOT_FOUND", f"Test case not found: {test_case_id}")
    return JSONResponse(
        content={
            "test_case_id": test_case.test_case_id,
            "target_node_id": test_case.target_node_id,
            "status": test_case.status.value,
            "scope_fingerprint": test_case.scope_fingerprint,
            "workflow_fingerprint": test_case.workflow_fingerprint,
            "nodes": {
                node_id: {
                    "status": node.status,
                    "node_type": node.node_type,
                    "error": node.error,
                    "has_output": node.output_ref is not None,
                }
                for node_id, node in test_case.nodes.items()
            },
            "input_identities": test_case.input_identities,
            "created_at": test_case.created_at.isoformat(),
            "expires_at": test_case.expires_at.isoformat() if test_case.expires_at else None,
        }
    )


@router.post("/adaptor-test-cases")
async def create_test_case_endpoint(
    request: Request,
    _run_ctx: WorkflowRunContext,
    workflow: str = Form(...),
    target_node_id: str = Form(...),
    files: UploadFilesParam = None,
    file_ids: str | None = Form(default=None),
) -> JSONResponse:
    settings = get_settings()

    try:
        workflow_payload = json.loads(workflow)
        definition = WorkflowDefinition.model_validate(workflow_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        return error_response(
            400,
            "WORKFLOW_VALIDATION_ERROR",
            f"Workflow JSON invalid: {exc}",
        )

    target_node = definition.get_node(target_node_id)
    if target_node is None:
        return error_response(400, "NODE_NOT_FOUND", f"Node not found: {target_node_id}")
    if target_node.type != "processor/adaptor":
        return error_response(
            400,
            "UNSUPPORTED_NODE_TYPE",
            f"Test Workbench only supports processor/adaptor nodes, got: {target_node.type}",
        )

    uploaded_files: list[UploadRecord] = []
    for upload in files or []:
        result = await validate_and_store_upload(upload, settings)
        if isinstance(result, JSONResponse):
            await cleanup_uploaded_files(uploaded_files, settings)
            return result
        uploaded_files.append(result)

    input_identities = _input_identities_from_request(files, file_ids)

    try:
        test_case = create_test_case(definition, target_node_id, input_identities)
    except ValueError as exc:
        await cleanup_uploaded_files(uploaded_files, settings)
        return error_response(400, "EMPTY_ANCESTOR_CLOSURE", str(exc))

    scope_ids = compute_ancestor_closure(
        definition.nodes,
        definition.connections,
        target_node_id,
        include_target=False,
    )

    scoped_nodes = [node.model_copy(deep=True) for node in definition.nodes if node.id in scope_ids]
    if uploaded_files:
        for node in scoped_nodes:
            file_value = node.config.get("file")
            if isinstance(file_value, str) and file_value.startswith("$file_"):
                node.config["file"] = str(uploaded_files[0]["storage_path"])

    last_ancestor_id = target_node_id
    for connection in reversed(definition.connections):
        if connection.target == target_node_id:
            last_ancestor_id = connection.source
            break

    scoped_connections = [
        connection.model_copy(deep=True)
        for connection in definition.connections
        if connection.source in scope_ids and connection.target in scope_ids
    ]
    if not any(node.type.startswith("end/") for node in scoped_nodes):
        scoped_nodes.append(WorkflowNode(id="end_1", type="end/final", config={}))
        scoped_connections.append(WorkflowConnection(source=last_ancestor_id, target="end_1"))

    scope_workflow = WorkflowDefinition(nodes=scoped_nodes, connections=scoped_connections)
    test_case.status = TestCaseStatus.running_upstream

    dag_scheduler = request.app.state.dag_scheduler
    engine_client = request.app.state.engine_client
    auth_resolver = getattr(request.app.state, "auth_resolver", None)
    provider_resolver = _provider_resolver_for_request(request, _run_ctx.workspace_id)

    input_bindings: dict[str, TaskInputFile] = {}
    for node in scoped_nodes:
        if node.type.startswith("input/") and uploaded_files:
            record = uploaded_files[0]
            input_bindings[node.id] = TaskInputFile(
                file_path=record["storage_path"],
                filename=record["filename"],
                mime_type=record["mime_type"],
                size_bytes=record["size_bytes"],
            )

    async def _execute_upstream() -> None:
        executor = make_node_executor(
            engine_client,
            auth_resolver=auth_resolver,
            provider_resolver=provider_resolver,
        )
        try:
            dag_result = await dag_scheduler.run(
                scope_workflow,
                node_executor=executor,
                run_id=f"atc_run_{test_case.test_case_id}",
                input_bindings=input_bindings or None,
            )
            completed = dag_result.completed
            for node_id, output in completed.items():
                if node_id in test_case.nodes:
                    update_node_status(
                        test_case.test_case_id,
                        node_id,
                        "completed",
                        output=output,
                    )

            for node_id in list(test_case.nodes.keys()):
                if node_id not in completed:
                    update_node_status(
                        test_case.test_case_id,
                        node_id,
                        "failed",
                        error={"message": "not completed"},
                    )

            finalize_test_case(test_case.test_case_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Test Case upstream execution failed for %s: %s",
                test_case.test_case_id,
                type(exc).__name__,
            )
            for node_id in list(test_case.nodes.keys()):
                if test_case.nodes[node_id].status == "pending":
                    update_node_status(
                        test_case.test_case_id,
                        node_id,
                        "failed",
                        error={"message": str(exc)},
                    )
            finalize_test_case(test_case.test_case_id)

    asyncio.get_running_loop().create_task(_execute_upstream())

    return JSONResponse(
        status_code=201,
        content={
            "test_case_id": test_case.test_case_id,
            "status": test_case.status.value,
            "target_node_id": test_case.target_node_id,
            "scope_fingerprint": test_case.scope_fingerprint,
            "workflow_fingerprint": test_case.workflow_fingerprint,
            "nodes": {
                node_id: {"status": node.status, "node_type": node.node_type}
                for node_id, node in test_case.nodes.items()
            },
            "input_identities": test_case.input_identities,
            "created_at": test_case.created_at.isoformat(),
            "expires_at": test_case.expires_at.isoformat() if test_case.expires_at else None,
        },
    )


@router.get("/adaptor-test-cases/{test_case_id}")
async def get_test_case_endpoint(
    test_case_id: str,
    _run_ctx: WorkflowRunContext,
) -> JSONResponse:
    return _test_case_response_payload(test_case_id)


@router.get("/adaptor-test-cases/{test_case_id}/nodes/{node_id}/result")
async def get_node_result_endpoint(
    test_case_id: str,
    node_id: str,
    _run_ctx: WorkflowRunContext,
) -> JSONResponse:
    test_case = get_test_case(test_case_id)
    if test_case is None:
        return error_response(404, "TEST_CASE_NOT_FOUND", f"Test case not found: {test_case_id}")

    if node_id not in test_case.nodes:
        return error_response(404, "NODE_NOT_IN_SCOPE", f"Node not in test case scope: {node_id}")

    node_info = test_case.nodes[node_id]
    if node_info.status != "completed":
        return error_response(
            409,
            "NODE_NOT_COMPLETED",
            f"Node status is '{node_info.status}', not 'completed'",
        )

    output = get_node_output(test_case_id, node_id)
    if output is None:
        return error_response(404, "OUTPUT_NOT_FOUND", f"Output not found for node: {node_id}")

    return JSONResponse(
        content={
            "node_id": node_id,
            "output": output.model_dump(mode="json"),
        }
    )


@router.delete("/adaptor-test-cases/{test_case_id}")
async def delete_test_case_endpoint(
    test_case_id: str,
    _run_ctx: WorkflowRunContext,
) -> JSONResponse:
    deleted = delete_test_case(test_case_id)
    if not deleted:
        return error_response(404, "TEST_CASE_NOT_FOUND", f"Test case not found: {test_case_id}")

    return JSONResponse(content={"deleted": True, "test_case_id": test_case_id})


@router.post("/adaptor-test-cases/{test_case_id}/executions")
async def create_execution_endpoint(
    test_case_id: str,
    _run_ctx: WorkflowRunContext,
    body: ExecutionBodyParam | None = None,
) -> JSONResponse:
    payload = body or {}
    test_case = get_test_case(test_case_id)
    if test_case is None:
        return error_response(404, "TEST_CASE_NOT_FOUND", f"Test case not found: {test_case_id}")

    if test_case.status == TestCaseStatus.stale:
        return error_response(409, "TEST_CASE_STALE", "Test case is stale. Refresh before testing.")

    if test_case.status != TestCaseStatus.ready:
        return error_response(
            409,
            "TEST_CASE_NOT_READY",
            f"Test case status is '{test_case.status.value}', must be 'ready'",
        )

    definition = get_test_case_definition(test_case_id)
    if definition is None:
        return error_response(404, "TEST_CASE_NOT_FOUND", f"Test case not found: {test_case_id}")

    code = payload.get("code", "")
    if not isinstance(code, str) or not code.strip():
        return error_response(400, "INVALID_REQUEST", "code must not be blank")
    input_mode = payload.get("input_mode", "all_upstream")
    bindings_raw = payload.get("bindings", [])
    bindings = bindings_raw if isinstance(bindings_raw, list) else []

    completed = get_completed_outputs(test_case_id)
    try:
        resolved = resolve_adaptor_inputs(
            definition=definition,
            target_node_id=test_case.target_node_id,
            completed_outputs=completed,
            input_mode=input_mode if isinstance(input_mode, str) else "all_upstream",
            bindings=bindings,
            trusted_scope=None,
        )
    except BindingResolutionError as exc:
        binding_result: ExecutionResultPayload = {
            "status": "failed",
            "output": None,
            "error": {
                "phase": "binding_resolution",
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": False,
            },
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
        }
        execution_id = store_execution(
            test_case_id,
            code,
            input_mode if isinstance(input_mode, str) else "all_upstream",
            bindings,
            binding_result,
        )
        return JSONResponse(
            status_code=200,
            content={"execution_id": execution_id, **binding_result},
        )
    except Exception as exc:  # noqa: BLE001
        resolution_result: ExecutionResultPayload = {
            "status": "failed",
            "output": None,
            "error": {
                "phase": "binding_resolution",
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": False,
            },
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
        }
        execution_id = store_execution(
            test_case_id,
            code,
            str(input_mode),
            bindings,
            resolution_result,
        )
        return JSONResponse(
            status_code=200,
            content={"execution_id": execution_id, **resolution_result},
        )

    settings = get_settings()
    broker_url = validate_adaptor_sandbox_broker_url(str(settings.adaptor_sandbox_broker_url))
    sandbox = SandboxClient(base_url=broker_url)

    started = time.perf_counter()
    result: ExecutionResultPayload
    try:
        prepared_inputs = await asyncio.to_thread(
            _inline_storage_root_binary_refs,
            resolved,
            storage_root=str(settings.storage_root),
            max_binary_item_bytes=SandboxLimits().max_binary_item_bytes,
        )
        await assert_adaptor_sandbox_ready(sandbox)
        output = await sandbox.process(
            request_id=f"{test_case_id}:{test_case.target_node_id}",
            code=code,
            inputs=prepared_inputs,
        )
        duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
        result = {
            "status": "succeeded",
            "output": output,
            "error": None,
            "stdout": "",
            "stderr": "",
            "duration_ms": duration_ms,
        }
    except Exception as exc:  # noqa: BLE001
        duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
        result = {
            "status": "failed",
            "output": None,
            "error": {
                "phase": "sandbox_transport",
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": False,
            },
            "stdout": "",
            "stderr": "",
            "duration_ms": duration_ms,
        }
    finally:
        await sandbox.close()

    execution_id = store_execution(
        test_case_id,
        code,
        input_mode if isinstance(input_mode, str) else "all_upstream",
        bindings,
        result,
    )

    output_payload = result["output"]
    if isinstance(output_payload, NodeOutput):
        output_json: dict[str, Any] | None = output_payload.model_dump(mode="json")
    elif isinstance(output_payload, dict):
        output_json = output_payload
    else:
        output_json = None

    return JSONResponse(
        status_code=200,
        content={
            "execution_id": execution_id,
            "status": result["status"],
            "output": output_json,
            "error": result["error"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "duration_ms": result["duration_ms"],
        },
    )


@router.get("/adaptor-test-cases/{test_case_id}/executions/{execution_id}")
async def get_execution_endpoint(
    test_case_id: str,
    execution_id: str,
    _run_ctx: WorkflowRunContext,
) -> JSONResponse:
    entry = get_execution(execution_id)
    if entry is None:
        return error_response(404, "EXECUTION_NOT_FOUND", f"Execution not found: {execution_id}")

    if entry["test_case_id"] != test_case_id:
        return error_response(
            404,
            "EXECUTION_NOT_FOUND",
            "Execution does not belong to this test case",
        )

    exec_model = entry["execution"]
    return JSONResponse(
        content={
            "execution_id": exec_model.execution_id,
            "test_case_id": exec_model.test_case_id,
            "status": exec_model.status.value,
            "output": exec_model.output,
            "error": exec_model.error.model_dump(mode="json") if exec_model.error else None,
            "stdout": exec_model.stdout,
            "stderr": exec_model.stderr,
            "duration_ms": exec_model.duration_ms,
            "created_at": exec_model.created_at.isoformat(),
        }
    )
