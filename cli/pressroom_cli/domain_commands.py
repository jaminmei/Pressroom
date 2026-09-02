from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable

from pressroom_cli.errors import TIMEOUT, USAGE, CliError
from pressroom_cli.io_utils import load_json_input, write_binary_atomic
from pressroom_cli.runtime import CommandResult, Runtime
from pressroom_cli.transport import ApiClient, ApiResponse

DOMAIN_ROOTS = {
    "workflow",
    "run",
    "test-set",
    "ground-truth",
    "evaluation",
    "provider",
    "engine",
    "node-type",
}


def _leaf(
    parent: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
) -> argparse.ArgumentParser:
    return parent.add_parser(name, help=help_text, description=help_text)


def _identifier(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument(name)


def _download_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")


def _confirmation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--yes", action="store_true")


def register_domain_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    workflow = _leaf(commands, "workflow", "manage workflows and versions")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    validate = _leaf(workflow_commands, "validate", "validate a workflow definition")
    validate.add_argument("--definition", required=True, metavar="JSON_FILE")
    workflow_list = _leaf(workflow_commands, "list", "list workflows")
    workflow_list.add_argument("--page", type=int, default=1)
    workflow_list.add_argument("--limit", type=int, default=20)
    workflow_list.add_argument("--sort", default="updated_at:desc")
    workflow_list.add_argument("--query")
    for name in ("get", "export"):
        parser = _leaf(workflow_commands, name, f"{name} a workflow")
        _identifier(parser, "workflow_id")
        if name == "export":
            _download_options(parser)
    create = _leaf(workflow_commands, "create", "create a workflow")
    create.add_argument("--name")
    create.add_argument("--description")
    create.add_argument("--definition", required=True, metavar="JSON_FILE")
    update = _leaf(workflow_commands, "update", "update workflow metadata or definition")
    _identifier(update, "workflow_id")
    update.add_argument("--name")
    update.add_argument("--description")
    update.add_argument("--clear-description", action="store_true")
    update.add_argument("--definition", metavar="JSON_FILE")
    update.add_argument("--base-version", type=int)
    imported = _leaf(workflow_commands, "import", "import a workflow export document")
    imported.add_argument("--input", required=True, metavar="JSON_FILE")
    for name in ("publish", "delete"):
        parser = _leaf(workflow_commands, name, f"{name} a workflow")
        _identifier(parser, "workflow_id")
        _confirmation(parser)
    execute = _leaf(workflow_commands, "execute", "execute a persisted workflow")
    _identifier(execute, "workflow_id")
    execute.add_argument("--version", type=int)
    execute.add_argument("--file-id", action="append", default=[])
    execute.add_argument("--run-name")
    _confirmation(execute)
    draft_run = _leaf(workflow_commands, "draft-run", "execute a draft workflow definition")
    draft_run.add_argument("--definition", required=True, metavar="JSON_FILE")
    draft_run.add_argument("--file-id", action="append", default=[])
    draft_run.add_argument("--run-name")
    _confirmation(draft_run)
    node_run = _leaf(workflow_commands, "node-run", "execute one node from a draft workflow")
    node_run.add_argument("--definition", required=True, metavar="JSON_FILE")
    node_run.add_argument("--node-id", required=True)
    node_run.add_argument("--file-id", action="append", default=[])
    _confirmation(node_run)
    version = _leaf(workflow_commands, "version", "inspect and restore workflow versions")
    version_commands = version.add_subparsers(dest="workflow_version_command", required=True)
    version_list = _leaf(version_commands, "list", "list workflow versions")
    _identifier(version_list, "workflow_id")
    version_get = _leaf(version_commands, "get", "get a workflow version")
    _identifier(version_get, "workflow_id")
    version_get.add_argument("version", type=int)
    version_restore = _leaf(version_commands, "restore", "restore a workflow version")
    _identifier(version_restore, "workflow_id")
    version_restore.add_argument("version", type=int)
    _confirmation(version_restore)

    run = _leaf(commands, "run", "inspect and control workflow runs")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_list = _leaf(run_commands, "list", "list runs")
    run_list.add_argument("--page", type=int, default=1)
    run_list.add_argument("--limit", type=int, default=20)
    run_list.add_argument("--status", default="all")
    run_list.add_argument("--workflow-id")
    for name in ("get", "results"):
        parser = _leaf(run_commands, name, f"{name} run data")
        _identifier(parser, "run_id")
    wait = _leaf(run_commands, "wait", "wait for a run to reach a terminal state")
    _identifier(wait, "run_id")
    wait.add_argument("--wait-timeout", type=float, default=600.0)
    wait.add_argument("--interval", type=float, default=2.0)
    download = _leaf(run_commands, "download", "download a run result")
    _identifier(download, "run_id")
    _identifier(download, "result_id")
    _download_options(download)
    for name in ("cancel", "retry"):
        parser = _leaf(run_commands, name, f"{name} a run")
        _identifier(parser, "run_id")
        _confirmation(parser)
    node = _leaf(run_commands, "node", "inspect run node outputs")
    node_commands = node.add_subparsers(dest="run_node_command", required=True)
    node_get = _leaf(node_commands, "get", "get a node result")
    _identifier(node_get, "run_id")
    _identifier(node_get, "node_id")
    node_image = _leaf(node_commands, "image", "download a node image")
    _identifier(node_image, "run_id")
    _identifier(node_image, "node_id")
    node_image.add_argument("--index", type=int, default=0)
    _download_options(node_image)

    test_set = _leaf(commands, "test-set", "manage test sets and documents")
    test_set_commands = test_set.add_subparsers(dest="test_set_command", required=True)
    _leaf(test_set_commands, "list", "list test sets")
    test_set_get = _leaf(test_set_commands, "get", "get a test set")
    _identifier(test_set_get, "test_set_id")
    test_set_create = _leaf(test_set_commands, "create", "create a test set")
    test_set_create.add_argument("--name", required=True)
    test_set_create.add_argument("--description")
    test_set_update = _leaf(test_set_commands, "update", "update a test set")
    _identifier(test_set_update, "test_set_id")
    test_set_update.add_argument("--name")
    test_set_update.add_argument("--description")
    test_set_update.add_argument("--clear-description", action="store_true")
    test_set_delete = _leaf(test_set_commands, "delete", "delete a test set")
    _identifier(test_set_delete, "test_set_id")
    _confirmation(test_set_delete)
    document = _leaf(test_set_commands, "document", "manage test-set documents")
    document_commands = document.add_subparsers(dest="document_command", required=True)
    document_list = _leaf(document_commands, "list", "list documents")
    _identifier(document_list, "test_set_id")
    document_get = _leaf(document_commands, "get", "get document metadata")
    _identifier(document_get, "test_set_id")
    _identifier(document_get, "document_id")
    for name in ("download", "thumbnail"):
        parser = _leaf(document_commands, name, f"download document {name}")
        _identifier(parser, "test_set_id")
        _identifier(parser, "document_id")
        if name == "thumbnail":
            parser.add_argument("--size", type=int, choices=(96, 640), default=96)
        _download_options(parser)
    document_upload = _leaf(document_commands, "upload", "upload one or more documents")
    _identifier(document_upload, "test_set_id")
    document_upload.add_argument("--file", action="append", required=True, dest="file_paths")
    _confirmation(document_upload)
    document_delete = _leaf(document_commands, "delete", "delete a document")
    _identifier(document_delete, "test_set_id")
    _identifier(document_delete, "document_id")
    _confirmation(document_delete)

    ground_truth = _leaf(commands, "ground-truth", "manage document ground truth")
    gt_commands = ground_truth.add_subparsers(dest="ground_truth_command", required=True)
    gt_get = _leaf(gt_commands, "get", "get latest ground truth")
    _document_selector(gt_get)
    gt_upload = _leaf(gt_commands, "upload", "create a ground-truth version")
    _document_selector(gt_upload)
    gt_upload.add_argument("--content", required=True, metavar="TEXT_FILE")
    gt_upload.add_argument("--format", default="text")
    gt_upload.add_argument("--source", default="cli")
    gt_upload.add_argument("--notes")
    _confirmation(gt_upload)
    gt_version = _leaf(gt_commands, "version", "inspect ground-truth versions")
    gt_version_commands = gt_version.add_subparsers(
        dest="ground_truth_version_command", required=True
    )
    gt_version_list = _leaf(gt_version_commands, "list", "list ground-truth versions")
    _document_selector(gt_version_list)
    gt_version_get = _leaf(gt_version_commands, "get", "get a ground-truth version")
    _document_selector(gt_version_get)
    gt_version_get.add_argument("version", type=int)

    evaluation = _leaf(commands, "evaluation", "manage evaluation runs")
    evaluation_commands = evaluation.add_subparsers(dest="evaluation_command", required=True)
    evaluation_list = _leaf(evaluation_commands, "list", "list evaluations for a test set")
    _identifier(evaluation_list, "test_set_id")
    for name in ("get", "results"):
        parser = _leaf(evaluation_commands, name, f"{name} evaluation data")
        _identifier(parser, "evaluation_id")
    evaluation_result = _leaf(evaluation_commands, "result", "get an evaluation result")
    _identifier(evaluation_result, "evaluation_id")
    _identifier(evaluation_result, "result_id")
    evaluation_wait = _leaf(evaluation_commands, "wait", "wait for an evaluation")
    _identifier(evaluation_wait, "evaluation_id")
    evaluation_wait.add_argument("--wait-timeout", type=float, default=600.0)
    evaluation_wait.add_argument("--interval", type=float, default=2.0)
    evaluation_create = _leaf(evaluation_commands, "create", "create an evaluation")
    _identifier(evaluation_create, "test_set_id")
    evaluation_create.add_argument("--workflow-id", required=True)
    evaluation_create.add_argument("--name")
    evaluation_create.add_argument("--document-id", action="append", default=[])
    evaluation_create.add_argument("--client-request-id")
    _confirmation(evaluation_create)
    evaluation_cancel = _leaf(evaluation_commands, "cancel", "cancel an evaluation")
    _identifier(evaluation_cancel, "evaluation_id")
    _confirmation(evaluation_cancel)
    comparison = _leaf(evaluation_commands, "comparison", "read or refresh comparison data")
    comparison_commands = comparison.add_subparsers(dest="comparison_command", required=True)
    for name in ("get", "refresh"):
        parser = _leaf(comparison_commands, name, f"{name} comparison data")
        _identifier(parser, "evaluation_id")
        _identifier(parser, "result_id")
        if name == "refresh":
            _confirmation(parser)

    provider = _leaf(commands, "provider", "discover and diagnose providers")
    provider_commands = provider.add_subparsers(dest="provider_command", required=True)
    provider_list = _leaf(provider_commands, "list", "list providers")
    provider_list.add_argument("--category")
    provider_list.add_argument("--provider-type")
    provider_list.add_argument("--all", action="store_true")
    provider_get = _leaf(provider_commands, "get", "get provider metadata")
    _identifier(provider_get, "provider_id")
    for name in ("test", "health"):
        parser = _leaf(provider_commands, name, f"run provider {name}")
        _identifier(parser, "provider_id")
        _confirmation(parser)
    provider_model = _leaf(provider_commands, "model", "discover and diagnose models")
    provider_model_commands = provider_model.add_subparsers(
        dest="provider_model_command", required=True
    )
    model_list = _leaf(provider_model_commands, "list", "list enabled provider models")
    model_list.add_argument("--category")
    model_test = _leaf(provider_model_commands, "test", "test a configured model")
    _identifier(model_test, "provider_id")
    _identifier(model_test, "model_id")
    _confirmation(model_test)

    engine = _leaf(commands, "engine", "discover and diagnose engine categories")
    engine_commands = engine.add_subparsers(dest="engine_command", required=True)
    _leaf(engine_commands, "list", "list engine categories")
    for name in ("get", "health"):
        parser = _leaf(engine_commands, name, f"{name} an engine category")
        _identifier(parser, "category")
        if name == "health":
            _confirmation(parser)
    node_type = _leaf(commands, "node-type", "discover workflow node types")
    node_type_commands = node_type.add_subparsers(dest="node_type_command", required=True)
    _leaf(node_type_commands, "list", "list workflow node types")


def _document_selector(parser: argparse.ArgumentParser) -> None:
    _identifier(parser, "test_set_id")
    _identifier(parser, "document_id")


def _client(runtime: Runtime, args: argparse.Namespace) -> ApiClient:
    return ApiClient(runtime.executor_context(), timeout=args.timeout)


def _json_input(runtime: Runtime, source: str) -> object:
    authorized = (
        source if source == "-" else str(runtime.executor_context().authorize_file_path(source))
    )
    return load_json_input(authorized, runtime.stdin)


def _text_input(runtime: Runtime, source: str) -> str:
    authorized = runtime.executor_context().authorize_file_path(source)
    try:
        return authorized.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError("Could not read text input", 8, "INPUT_READ_FAILED") from exc


def _confirm(runtime: Runtime, prompt: str, yes: bool) -> None:
    if yes:
        return
    if not getattr(runtime.stdin, "isatty", lambda: False)():
        raise CliError(
            "Confirmation requires Tool Executor approval",
            USAGE,
            "CONFIRMATION_REQUIRED",
        )
    runtime.stderr.write(f"{prompt} [y/N] ")
    runtime.stderr.flush()
    if runtime.stdin.readline().strip().lower() not in {"y", "yes"}:
        raise CliError("Action cancelled", USAGE, "ACTION_CANCELLED")


def _result(response: ApiResponse, *, exit_code: int = 0) -> CommandResult:
    return CommandResult(response.data, response.request_id, exit_code)


def _diagnostic_result(response: ApiResponse) -> CommandResult:
    status = response.data.get("status") if isinstance(response.data, dict) else None
    exit_code = 0 if status == "healthy" else 11
    return _result(response, exit_code=exit_code)


def _binary_result(
    runtime: Runtime,
    response: ApiResponse,
    *,
    output: str,
    force: bool,
    identity: dict[str, object],
) -> CommandResult:
    if response.raw is None:
        raise CliError("Platform did not return binary content", 11, "INVALID_BINARY_RESPONSE")
    destination = write_binary_atomic(
        str(runtime.executor_context().authorize_file_path(output)),
        response.raw,
        force=force,
    )
    return CommandResult(
        {
            **identity,
            "output": str(destination),
            "size_bytes": len(response.raw),
            "content_type": response.content_type,
        },
        response.request_id,
    )


def _wait(
    client: ApiClient,
    path: str,
    *,
    wait_timeout: float,
    interval: float,
    terminal: set[str],
) -> CommandResult:
    if wait_timeout <= 0 or interval <= 0:
        raise CliError("wait timeout and interval must be positive", USAGE, "CLI_USAGE")
    deadline = time.monotonic() + wait_timeout
    while True:
        response = client.request("GET", path)
        payload = response.data
        nested = payload.get("data") if isinstance(payload, dict) else None
        status = (payload.get("status") if isinstance(payload, dict) else None) or (
            nested.get("status") if isinstance(nested, dict) else None
        )
        if isinstance(status, str) and status.lower() in terminal:
            return _result(response)
        if time.monotonic() >= deadline:
            raise CliError(
                "Wait timed out; the remote operation was not cancelled",
                TIMEOUT,
                "WAIT_TIMEOUT",
                {"last_status": status},
                response.request_id,
            )
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def dispatch_domain(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    handlers: dict[str, Callable[[Runtime, argparse.Namespace], CommandResult]] = {
        "workflow": _workflow,
        "run": _run,
        "test-set": _test_set,
        "ground-truth": _ground_truth,
        "evaluation": _evaluation,
        "provider": _provider,
        "engine": _engine,
        "node-type": _node_type,
    }
    return handlers[args.root_command](runtime, args)


def _workflow(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    command = args.workflow_command
    if command == "validate":
        return _result(
            client.request(
                "POST",
                "/api/workflows/validate",
                body=_json_input(runtime, args.definition),
            )
        )
    if command == "list":
        query = {
            "page": str(args.page),
            "limit": str(args.limit),
            "sort": args.sort,
        }
        if args.query:
            query["q"] = args.query
        return _result(client.request("GET", "/api/workflows", query=query))
    if command == "get":
        return _result(client.request("GET", f"/api/workflows/{args.workflow_id}"))
    if command == "export":
        response = client.request("GET", f"/api/workflows/{args.workflow_id}/export")
        content = response.raw
        if content is None:
            content = json.dumps(response.data, ensure_ascii=False, indent=2).encode("utf-8")
            response = ApiResponse(
                response.data, response.status, response.request_id, "application/json", content
            )
        return _binary_result(
            runtime,
            response,
            output=args.output,
            force=args.force,
            identity={"workflow_id": args.workflow_id},
        )
    if command == "create":
        create_body = {
            "name": args.name,
            "description": args.description,
            "definition": _json_input(runtime, args.definition),
        }
        return _result(client.request("POST", "/api/workflows", body=create_body))
    if command == "update":
        update_body: dict[str, object] = {}
        if args.name is not None:
            update_body["name"] = args.name
        if args.description is not None or args.clear_description:
            update_body["description"] = None if args.clear_description else args.description
        if args.definition:
            if args.base_version is None:
                raise CliError(
                    "--base-version is required with --definition",
                    USAGE,
                    "CLI_USAGE",
                )
            update_body["definition"] = _json_input(runtime, args.definition)
            update_body["base_version"] = args.base_version
        if not update_body:
            raise CliError("At least one update field is required", USAGE, "CLI_USAGE")
        return _result(
            client.request(
                "PATCH",
                f"/api/workflows/{args.workflow_id}",
                body=update_body,
            )
        )
    if command == "import":
        return _result(
            client.request("POST", "/api/workflows/import", body=_json_input(runtime, args.input))
        )
    if command in {"publish", "delete"}:
        if command == "delete":
            impact = client.request(
                "GET",
                f"/api/workflows/{args.workflow_id}/deletion-impact",
            )
            if isinstance(impact.data, dict) and not impact.data.get("can_delete", False):
                raise CliError(
                    "Workflow has active references",
                    6,
                    "WORKFLOW_IN_USE",
                    impact.data,
                    impact.request_id,
                )
        _confirm(runtime, f"{command.title()} workflow {args.workflow_id}?", args.yes)
        method = "POST" if command == "publish" else "DELETE"
        return _result(
            client.request(
                method,
                f"/api/workflows/{args.workflow_id}/{command}"
                if command == "publish"
                else f"/api/workflows/{args.workflow_id}",
            )
        )
    if command == "version":
        path = f"/api/workflows/{args.workflow_id}/versions"
        if args.workflow_version_command == "list":
            return _result(client.request("GET", path))
        path = f"{path}/{args.version}"
        if args.workflow_version_command == "get":
            return _result(client.request("GET", path))
        _confirm(
            runtime, f"Restore workflow {args.workflow_id} to version {args.version}?", args.yes
        )
        return _result(client.request("POST", f"{path}/restore"))
    if command == "execute":
        _confirm(runtime, f"Execute workflow {args.workflow_id}?", args.yes)
        body = {"file_ids": args.file_id, "version": args.version, "run_name": args.run_name}
        return _result(
            client.request("POST", f"/api/workflows/{args.workflow_id}/execute", body=body)
        )
    definition = _json_input(runtime, args.definition)
    _confirm(runtime, f"Execute {command}?", args.yes)
    fields = {
        "workflow": json.dumps(definition, ensure_ascii=False),
        "file_ids": json.dumps(args.file_id),
    }
    if args.run_name:
        fields["run_name"] = args.run_name
    if command == "node-run":
        fields["node_id"] = args.node_id
    path = "/api/workflow-draft-runs/node" if command == "node-run" else "/api/workflow-draft-runs"
    return _result(client.multipart_request("POST", path, files=[], fields=fields))


def _run(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    command = args.run_command
    if command == "list":
        query = {"page": str(args.page), "limit": str(args.limit), "status": args.status}
        if args.workflow_id:
            query["workflow_id"] = args.workflow_id
        return _result(client.request("GET", "/api/tasks/history", query=query))
    if command == "get":
        return _result(client.request("GET", f"/api/tasks/{args.run_id}"))
    if command == "wait":
        return _wait(
            client,
            f"/api/tasks/{args.run_id}",
            wait_timeout=args.wait_timeout,
            interval=args.interval,
            terminal={"completed", "partial_completed", "failed", "cancelled"},
        )
    if command == "results":
        return _result(client.request("GET", f"/api/tasks/{args.run_id}/results"))
    if command == "download":
        response = client.request(
            "GET", f"/api/tasks/{args.run_id}/results/{args.result_id}/download"
        )
        return _binary_result(
            runtime,
            response,
            output=args.output,
            force=args.force,
            identity={"run_id": args.run_id, "result_id": args.result_id},
        )
    if command in {"cancel", "retry"}:
        _confirm(runtime, f"{command.title()} run {args.run_id}?", args.yes)
        method = "DELETE" if command == "cancel" else "POST"
        suffix = "" if command == "cancel" else "/retry"
        return _result(client.request(method, f"/api/tasks/{args.run_id}{suffix}"))
    path = f"/api/tasks/{args.run_id}/nodes/{args.node_id}"
    if args.run_node_command == "get":
        return _result(client.request("GET", f"{path}/result"))
    response = client.request("GET", f"{path}/image", query={"index": str(args.index)})
    return _binary_result(
        runtime,
        response,
        output=args.output,
        force=args.force,
        identity={"run_id": args.run_id, "node_id": args.node_id, "index": args.index},
    )


def _test_set(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    command = args.test_set_command
    if command == "list":
        return _result(client.request("GET", "/api/test-sets"))
    if command == "get":
        return _result(client.request("GET", f"/api/test-sets/{args.test_set_id}"))
    if command == "create":
        return _result(
            client.request(
                "POST", "/api/test-sets", body={"name": args.name, "description": args.description}
            )
        )
    if command == "update":
        body: dict[str, object] = {}
        if args.name is not None:
            body["name"] = args.name
        if args.description is not None or args.clear_description:
            body["description"] = None if args.clear_description else args.description
        if not body:
            raise CliError("At least one update field is required", USAGE, "CLI_USAGE")
        return _result(client.request("PATCH", f"/api/test-sets/{args.test_set_id}", body=body))
    if command == "delete":
        impact = client.request("GET", f"/api/test-sets/{args.test_set_id}/deletion-impact")
        if isinstance(impact.data, dict) and not impact.data.get("can_delete", False):
            raise CliError(
                "Test set has active evaluations",
                6,
                "TEST_SET_IN_USE",
                impact.data,
                impact.request_id,
            )
        _confirm(runtime, f"Delete test set {args.test_set_id}?", args.yes)
        return _result(client.request("DELETE", f"/api/test-sets/{args.test_set_id}"))
    base = f"/api/test-sets/{args.test_set_id}/documents"
    if args.document_command == "list":
        return _result(client.request("GET", base))
    if args.document_command == "get":
        return _result(client.request("GET", f"{base}/{args.document_id}"))
    if args.document_command in {"download", "thumbnail"}:
        suffix = "file" if args.document_command == "download" else "thumbnail"
        query = {"size": str(args.size)} if args.document_command == "thumbnail" else None
        response = client.request("GET", f"{base}/{args.document_id}/{suffix}", query=query)
        return _binary_result(
            runtime,
            response,
            output=args.output,
            force=args.force,
            identity={"test_set_id": args.test_set_id, "document_id": args.document_id},
        )
    if args.document_command == "upload":
        _confirm(
            runtime,
            f"Upload {len(args.file_paths)} document(s) to test set {args.test_set_id}?",
            args.yes,
        )
        response = client.multipart_request(
            "POST", f"{base}/upload", files=[("files", path) for path in args.file_paths]
        )
        batch_status = response.data.get("status") if isinstance(response.data, dict) else None
        if batch_status == "failure":
            raise CliError(
                "All document uploads failed",
                7,
                "BATCH_UPLOAD_FAILED",
                response.data,
                response.request_id,
            )
        exit_code = 12 if batch_status == "partial" else 0
        return _result(response, exit_code=exit_code)
    impact = client.request("GET", f"{base}/{args.document_id}/deletion-impact")
    if isinstance(impact.data, dict) and not impact.data.get("can_delete", False):
        raise CliError(
            "Document has active evaluations", 6, "DOCUMENT_IN_USE", impact.data, impact.request_id
        )
    _confirm(runtime, f"Delete document {args.document_id}?", args.yes)
    return _result(client.request("DELETE", f"{base}/{args.document_id}"))


def _ground_truth(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    base = f"/api/test-sets/{args.test_set_id}/documents/{args.document_id}/ground-truth"
    if args.ground_truth_command == "get":
        return _result(client.request("GET", base))
    if args.ground_truth_command == "upload":
        _confirm(runtime, f"Create ground truth for document {args.document_id}?", args.yes)
        try:
            content = _text_input(runtime, args.content)
        except OSError as exc:
            raise CliError("Could not read ground-truth content", 8, "INPUT_READ_FAILED") from exc
        return _result(
            client.request(
                "POST",
                base,
                body={
                    "content": content,
                    "format": args.format,
                    "source": args.source,
                    "notes": args.notes,
                },
            )
        )
    path = f"{base}/versions"
    if args.ground_truth_version_command == "list":
        return _result(client.request("GET", path))
    return _result(client.request("GET", f"{path}/{args.version}"))


def _evaluation(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    command = args.evaluation_command
    if command == "list":
        return _result(client.request("GET", f"/api/test-sets/{args.test_set_id}/evaluation-runs"))
    if command == "get":
        return _result(client.request("GET", f"/api/evaluation-runs/{args.evaluation_id}"))
    if command == "wait":
        return _wait(
            client,
            f"/api/evaluation-runs/{args.evaluation_id}",
            wait_timeout=args.wait_timeout,
            interval=args.interval,
            terminal={"completed", "partial_completed", "failed", "cancelled"},
        )
    if command == "results":
        return _result(client.request("GET", f"/api/evaluation-runs/{args.evaluation_id}/results"))
    if command == "result":
        return _result(
            client.request(
                "GET", f"/api/evaluation-runs/{args.evaluation_id}/results/{args.result_id}"
            )
        )
    if command == "create":
        _confirm(runtime, f"Create evaluation for test set {args.test_set_id}?", args.yes)
        body = {
            "workflow_id": args.workflow_id,
            "name": args.name,
            "document_ids": args.document_id or None,
            "client_request_id": args.client_request_id,
        }
        return _result(
            client.request("POST", f"/api/test-sets/{args.test_set_id}/evaluation-runs", body=body)
        )
    if command == "cancel":
        _confirm(runtime, f"Cancel evaluation {args.evaluation_id}?", args.yes)
        return _result(client.request("POST", f"/api/evaluation-runs/{args.evaluation_id}/cancel"))
    path = f"/api/evaluation-runs/{args.evaluation_id}/results/{args.result_id}/comparison"
    method = "GET" if args.comparison_command == "get" else "POST"
    if method == "POST":
        _confirm(runtime, f"Refresh comparison for result {args.result_id}?", args.yes)
    return _result(client.request(method, path))


def _provider(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    command = args.provider_command
    if command == "list":
        query = {"enabled_only": "false" if args.all else "true"}
        if args.category:
            query["category"] = args.category
        if args.provider_type:
            query["provider_type"] = args.provider_type
        return _result(client.request("GET", "/api/providers", query=query))
    if command == "get":
        return _result(client.request("GET", f"/api/providers/{args.provider_id}"))
    if command in {"test", "health"}:
        _confirm(runtime, f"Run provider {command} for {args.provider_id}?", args.yes)
        suffix = "test" if command == "test" else "health-check"
        return _diagnostic_result(
            client.request("POST", f"/api/providers/{args.provider_id}/{suffix}")
        )
    if args.provider_model_command == "list":
        model_query = {"category": args.category} if args.category else None
        return _result(client.request("GET", "/api/models", query=model_query))
    _confirm(runtime, f"Test model {args.model_id}?", args.yes)
    return _diagnostic_result(
        client.request("POST", f"/api/providers/{args.provider_id}/models/{args.model_id}/test")
    )


def _engine(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    if args.engine_command == "list":
        return _result(client.request("GET", "/api/engines"))
    path = f"/api/engines/{args.category}"
    if args.engine_command == "get":
        return _result(client.request("GET", path))
    _confirm(runtime, f"Run engine health check for {args.category}?", args.yes)
    return _diagnostic_result(client.request("GET", f"{path}/health"))


def _node_type(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    return _result(_client(runtime, args).request("GET", "/api/nodes/registry"))
