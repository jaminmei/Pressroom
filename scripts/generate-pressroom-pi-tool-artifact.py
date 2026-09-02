#!/usr/bin/env python3
"""Generate the built-in Pi tool artifact from the canonical CLI catalog."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "cli" / "catalog" / "tool-catalog.yaml"
OUTPUT_PATHS = (
    ROOT / "cli" / "catalog" / "agent-tool-catalog.generated.json",
    ROOT / "pi_runtime" / "src" / "pressroom_tool_catalog.generated.json",
)

# Reviewed model-callable product boundary. Local-path I/O and UI-only
# administration intentionally stay outside the Agent runtime.
SELECTED_OPERATIONS = (
    "workflow.validate",
    "workflow.list",
    "workflow.get",
    "workflow.create",
    "workflow.update",
    "workflow.version.list",
    "workflow.version.get",
    "workflow.execute",
    "workflow.publish",
    "workflow.delete",
    "workflow.version.restore",
    "workflow.draft-run",
    "workflow.node-run",
    "run.list",
    "run.get",
    "run.wait",
    "run.results",
    "run.cancel",
    "run.retry",
    "run.node.get",
    "file.list",
    "file.get",
    "test-set.list",
    "test-set.get",
    "test-set.document.list",
    "test-set.document.get",
    "ground-truth.get",
    "ground-truth.version.list",
    "ground-truth.version.get",
    "evaluation.list",
    "evaluation.get",
    "evaluation.wait",
    "evaluation.results",
    "evaluation.result",
    "evaluation.create",
    "evaluation.cancel",
    "evaluation.comparison.get",
    "provider.list",
    "provider.get",
    "provider.model.list",
    "node-type.list",
)


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description, "minLength": 1, "maxLength": 2000}


def _integer(description: str, *, default: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "integer",
        "description": description,
        "minimum": 1,
        "maximum": 1_000_000,
    }
    if default is not None:
        result["default"] = default
    return result


def _number(description: str, *, default: float, minimum: float, maximum: float) -> dict[str, Any]:
    return {
        "type": "number",
        "description": description,
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
    }


def _string_array(description: str, *, maximum: int = 100) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "items": _string("Resource id."),
        "maxItems": maximum,
    }


def _details(
    operation: str,
    label: str,
    description: str,
    properties: dict[str, Any] | None = None,
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties or {},
    }
    if required:
        parameters["required"] = list(required)
    return {
        "name": operation.replace(".", "_").replace("-", "_"),
        "label": label,
        "description": description,
        "parameters": parameters,
    }


WORKFLOW_ID = _string("Workflow id.")
RUN_ID = _string("Workflow run id.")
TEST_SET_ID = _string("Test set id.")
DOCUMENT_ID = _string("Test-set document id.")
EVALUATION_ID = _string("Evaluation run id.")
RESULT_ID = _string("Evaluation result id.")
PROVIDER_ID = _string("Provider id.")
VERSION = _integer("Positive version number.")
DEFINITION = {"type": "object", "description": "Workflow definition JSON."}
FILE_IDS = _string_array("Workspace file ids selected or uploaded by the user.")
DOCUMENT_IDS = _string_array("Optional test-set document ids.", maximum=1000)

TOOL_DETAILS: dict[str, dict[str, Any]] = {
    "workflow.validate": _details(
        "workflow.validate",
        "Validate workflow",
        "Validate a structured workflow definition in the current workspace.",
        {"definition": DEFINITION},
        required=("definition",),
    ),
    "workflow.list": _details(
        "workflow.list",
        "List workflows",
        "List workflows visible in the current PressRoom workspace.",
        {
            "page": {**_integer("One-based result page.", default=1), "maximum": 100_000},
            "limit": {**_integer("Number of workflows to return.", default=20), "maximum": 200},
            "sort": _string("Stable sort expression, for example updated_at:desc."),
            "query": _string("Optional workflow name search."),
        },
    ),
    "workflow.get": _details(
        "workflow.get",
        "Get workflow",
        "Get one workflow from the current workspace.",
        {"workflow_id": WORKFLOW_ID},
        required=("workflow_id",),
    ),
    "workflow.create": _details(
        "workflow.create",
        "Create workflow",
        "Create a workflow from a structured definition after user approval.",
        {
            "name": _string("Workflow name."),
            "description": _string("Optional workflow description."),
            "definition": DEFINITION,
        },
        required=("definition",),
    ),
    "workflow.update": _details(
        "workflow.update",
        "Update workflow",
        "Update workflow metadata or definition after user approval.",
        {
            "workflow_id": WORKFLOW_ID,
            "name": _string("New workflow name."),
            "description": _string("New workflow description."),
            "clear_description": {"type": "boolean", "description": "Clear the description."},
            "definition": DEFINITION,
            "base_version": VERSION,
        },
        required=("workflow_id",),
    ),
    "workflow.version.list": _details(
        "workflow.version.list",
        "List workflow versions",
        "List durable versions of a workflow.",
        {"workflow_id": WORKFLOW_ID},
        required=("workflow_id",),
    ),
    "workflow.version.get": _details(
        "workflow.version.get",
        "Get workflow version",
        "Get a durable workflow version.",
        {"workflow_id": WORKFLOW_ID, "version": VERSION},
        required=("workflow_id", "version"),
    ),
    "workflow.execute": _details(
        "workflow.execute",
        "Execute workflow",
        "Execute a persisted workflow with user-selected workspace files after approval.",
        {
            "workflow_id": WORKFLOW_ID,
            "version": VERSION,
            "file_ids": FILE_IDS,
            "run_name": _string("Optional run name."),
        },
        required=("workflow_id",),
    ),
    "workflow.publish": _details(
        "workflow.publish",
        "Publish workflow",
        "Publish a workflow after user approval.",
        {"workflow_id": WORKFLOW_ID},
        required=("workflow_id",),
    ),
    "workflow.delete": _details(
        "workflow.delete",
        "Delete workflow",
        "Delete an unreferenced workflow after user approval.",
        {"workflow_id": WORKFLOW_ID},
        required=("workflow_id",),
    ),
    "workflow.version.restore": _details(
        "workflow.version.restore",
        "Restore workflow version",
        "Restore a workflow version after user approval.",
        {"workflow_id": WORKFLOW_ID, "version": VERSION},
        required=("workflow_id", "version"),
    ),
    "workflow.draft-run": _details(
        "workflow.draft-run",
        "Run workflow draft",
        "Execute a structured workflow draft with user-selected files after approval.",
        {"definition": DEFINITION, "file_ids": FILE_IDS, "run_name": _string("Run name.")},
        required=("definition",),
    ),
    "workflow.node-run": _details(
        "workflow.node-run",
        "Run draft node",
        "Execute one node from a structured workflow draft after approval.",
        {"definition": DEFINITION, "node_id": _string("Node id."), "file_ids": FILE_IDS},
        required=("definition", "node_id"),
    ),
    "run.list": _details(
        "run.list",
        "List runs",
        "List workflow runs in the current workspace.",
        {
            "page": {**_integer("One-based result page.", default=1), "maximum": 100_000},
            "limit": {**_integer("Number of runs to return.", default=20), "maximum": 200},
            "status": _string("Run status filter, or all."),
            "workflow_id": WORKFLOW_ID,
        },
    ),
    "run.get": _details(
        "run.get", "Get run", "Get workflow run metadata.", {"run_id": RUN_ID}, required=("run_id",)
    ),
    "run.wait": _details(
        "run.wait",
        "Wait for run",
        "Wait for a workflow run to reach a terminal state.",
        {
            "run_id": RUN_ID,
            "wait_timeout": _number("Maximum wait in seconds.", default=30, minimum=1, maximum=297),
            "interval": _number("Polling interval in seconds.", default=2, minimum=0.1, maximum=60),
        },
        required=("run_id",),
    ),
    "run.results": _details(
        "run.results",
        "Get run results",
        "Get workflow run results.",
        {"run_id": RUN_ID},
        required=("run_id",),
    ),
    "run.cancel": _details(
        "run.cancel",
        "Cancel run",
        "Cancel a workflow run after user approval.",
        {"run_id": RUN_ID},
        required=("run_id",),
    ),
    "run.retry": _details(
        "run.retry",
        "Retry run",
        "Retry a workflow run after user approval.",
        {"run_id": RUN_ID},
        required=("run_id",),
    ),
    "run.node.get": _details(
        "run.node.get",
        "Get run node result",
        "Get the result for one node in a workflow run.",
        {"run_id": RUN_ID, "node_id": _string("Node id.")},
        required=("run_id", "node_id"),
    ),
    "file.list": _details(
        "file.list",
        "List files",
        "List workspace file metadata. Files are uploaded by the user, not by the Agent.",
        {
            "page": {**_integer("One-based result page.", default=1), "maximum": 100_000},
            "limit": {**_integer("Number of files to return.", default=50), "maximum": 200},
            "query": _string("Optional file name search."),
        },
    ),
    "file.get": _details(
        "file.get",
        "Get file",
        "Get workspace file metadata.",
        {"file_id": _string("Workspace file id.")},
        required=("file_id",),
    ),
    "test-set.list": _details(
        "test-set.list", "List test sets", "List test sets in the current workspace."
    ),
    "test-set.get": _details(
        "test-set.get",
        "Get test set",
        "Get test-set metadata.",
        {"test_set_id": TEST_SET_ID},
        required=("test_set_id",),
    ),
    "test-set.document.list": _details(
        "test-set.document.list",
        "List test-set documents",
        "List documents in a test set.",
        {"test_set_id": TEST_SET_ID},
        required=("test_set_id",),
    ),
    "test-set.document.get": _details(
        "test-set.document.get",
        "Get test-set document",
        "Get test-set document metadata.",
        {"test_set_id": TEST_SET_ID, "document_id": DOCUMENT_ID},
        required=("test_set_id", "document_id"),
    ),
    "ground-truth.get": _details(
        "ground-truth.get",
        "Get ground truth",
        "Get the latest ground truth for a test-set document.",
        {"test_set_id": TEST_SET_ID, "document_id": DOCUMENT_ID},
        required=("test_set_id", "document_id"),
    ),
    "ground-truth.version.list": _details(
        "ground-truth.version.list",
        "List ground-truth versions",
        "List ground-truth versions for a test-set document.",
        {"test_set_id": TEST_SET_ID, "document_id": DOCUMENT_ID},
        required=("test_set_id", "document_id"),
    ),
    "ground-truth.version.get": _details(
        "ground-truth.version.get",
        "Get ground-truth version",
        "Get a ground-truth version for a test-set document.",
        {"test_set_id": TEST_SET_ID, "document_id": DOCUMENT_ID, "version": VERSION},
        required=("test_set_id", "document_id", "version"),
    ),
    "evaluation.list": _details(
        "evaluation.list",
        "List evaluations",
        "List evaluation runs for a test set.",
        {"test_set_id": TEST_SET_ID},
        required=("test_set_id",),
    ),
    "evaluation.get": _details(
        "evaluation.get",
        "Get evaluation",
        "Get evaluation metadata.",
        {"evaluation_id": EVALUATION_ID},
        required=("evaluation_id",),
    ),
    "evaluation.wait": _details(
        "evaluation.wait",
        "Wait for evaluation",
        "Wait for an evaluation to reach a terminal state.",
        {
            "evaluation_id": EVALUATION_ID,
            "wait_timeout": _number("Maximum wait in seconds.", default=30, minimum=1, maximum=297),
            "interval": _number("Polling interval in seconds.", default=2, minimum=0.1, maximum=60),
        },
        required=("evaluation_id",),
    ),
    "evaluation.results": _details(
        "evaluation.results",
        "Get evaluation results",
        "List results for an evaluation.",
        {"evaluation_id": EVALUATION_ID},
        required=("evaluation_id",),
    ),
    "evaluation.result": _details(
        "evaluation.result",
        "Get evaluation result",
        "Get one evaluation result.",
        {"evaluation_id": EVALUATION_ID, "result_id": RESULT_ID},
        required=("evaluation_id", "result_id"),
    ),
    "evaluation.create": _details(
        "evaluation.create",
        "Create evaluation",
        "Create an evaluation for a test set and workflow after user approval.",
        {
            "test_set_id": TEST_SET_ID,
            "workflow_id": WORKFLOW_ID,
            "name": _string("Optional evaluation name."),
            "document_ids": DOCUMENT_IDS,
            "client_request_id": _string("Optional idempotency key."),
        },
        required=("test_set_id", "workflow_id"),
    ),
    "evaluation.cancel": _details(
        "evaluation.cancel",
        "Cancel evaluation",
        "Cancel an evaluation after user approval.",
        {"evaluation_id": EVALUATION_ID},
        required=("evaluation_id",),
    ),
    "evaluation.comparison.get": _details(
        "evaluation.comparison.get",
        "Get evaluation comparison",
        "Get comparison data for one evaluation result.",
        {"evaluation_id": EVALUATION_ID, "result_id": RESULT_ID},
        required=("evaluation_id", "result_id"),
    ),
    "provider.list": _details(
        "provider.list",
        "List providers",
        "List provider metadata visible in the current workspace.",
        {
            "category": _string("Optional engine category."),
            "provider_type": _string("Optional provider type."),
            "all": {
                "type": "boolean",
                "description": "Include disabled providers.",
                "default": False,
            },
        },
    ),
    "provider.get": _details(
        "provider.get",
        "Get provider",
        "Get provider metadata.",
        {"provider_id": PROVIDER_ID},
        required=("provider_id",),
    ),
    "provider.model.list": _details(
        "provider.model.list",
        "List provider models",
        "List enabled provider model metadata.",
        {"category": _string("Optional engine category.")},
    ),
    "node-type.list": _details(
        "node-type.list", "List node types", "List workflow node types available on the platform."
    ),
}


def _catalog_metadata() -> tuple[str, dict[str, dict[str, Any]]]:
    """Read the catalog projection needed by this dependency-free generator."""

    schema_version = ""
    commands: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    quoted_value = re.compile(r'^    ([a-z_]+):\s+"([^"]*)"\s*$')
    boolean_value = re.compile(r"^    ([a-z_]+):\s+(true|false)\s*$")
    for line in CATALOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("schema_version:"):
            schema_version = line.partition(":")[2].strip().strip('"')
            continue
        match_id = re.match(r'^  - id:\s+"([^"]+)"\s*$', line)
        if match_id:
            current = {"id": match_id.group(1)}
            commands[current["id"]] = current
            continue
        if current is None:
            continue
        match_quoted = quoted_value.match(line)
        if match_quoted:
            current[match_quoted.group(1)] = match_quoted.group(2)
            continue
        match_boolean = boolean_value.match(line)
        if match_boolean:
            current[match_boolean.group(1)] = match_boolean.group(2) == "true"
    if not schema_version:
        raise RuntimeError("Tool catalog schema version is missing")
    return schema_version, commands


def build_artifact() -> dict[str, Any]:
    catalog_version, commands = _catalog_metadata()
    if set(SELECTED_OPERATIONS) != set(TOOL_DETAILS):
        raise RuntimeError("Selected operations and tool details do not match")
    tools: list[dict[str, Any]] = []
    for operation in SELECTED_OPERATIONS:
        command = commands.get(operation)
        if command is None or command.get("status") != "cli-ready":
            raise RuntimeError(f"Selected operation is not CLI-ready: {operation}")
        if command.get("exposure") == "agent-confirmation" and not command.get(
            "requires_platform_approval"
        ):
            raise RuntimeError(f"Confirmation tool lacks platform approval: {operation}")
        tools.append(
            {
                **TOOL_DETAILS[operation],
                "operation": operation,
                "exposure": command["exposure"],
                "capability": command.get("capability"),
                "command": command["command"],
                "requires_platform_approval": command.get("requires_platform_approval", False),
            }
        )
    return {"catalog_version": catalog_version, "tools": tools}


def render() -> str:
    return json.dumps(build_artifact(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        for output_path in OUTPUT_PATHS:
            if not output_path.is_file() or output_path.read_text(encoding="utf-8") != expected:
                raise SystemExit(f"PressRoom Pi tool artifact is stale: {output_path}")
        return 0
    for output_path in OUTPUT_PATHS:
        output_path.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
