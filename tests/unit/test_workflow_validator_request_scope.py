from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI, Request

from app.api.workflows import get_workflow_validator
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode


def _request_for(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/workflows/validate",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


def test_workflow_validator_uses_only_the_request_apps_provider_store() -> None:
    request_app = FastAPI()
    request_app.state.provider_store = MagicMock()
    request_app.state.provider_store.get_for_runtime.return_value = None
    definition = WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="engine",
                type="engine/text",
                config={"provider_id": "provider_from_another_workspace"},
            ),
            WorkflowNode(id="end", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input", target="engine"),
            WorkflowConnection(source="engine", target="end"),
        ],
    )

    result = get_workflow_validator(_request_for(request_app)).validate_for_publish(
        definition,
        workspace_id="ws_request",
    )

    assert "PROVIDER_NOT_FOUND" in {error.code for error in result.errors}
    request_app.state.provider_store.get_for_runtime.assert_called_once_with(
        "provider_from_another_workspace",
        "ws_request",
    )
