"""Workspace ownership checks for staged uploads."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.task import TaskInputFile
from app.models.workflow import WorkflowDefinition, WorkflowNode
from app.services.file_store import FileStore, UploadedFileRecord
from app.services.task_orchestrator import TaskOrchestrator

pytestmark = pytest.mark.usefixtures("file_resource_database")


def test_staged_file_is_shared_inside_its_workspace() -> None:
    # Given
    store = FileStore()
    store.put(
        UploadedFileRecord(
            file_id="file_owned",
            storage_path="/tmp/owned.pdf",
            filename="owned.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            workspace_id="ws_a",
            uploaded_by_user_id="usr_a",
            created_at=datetime.now(timezone.utc),
        )
    )

    # When / Then
    assert store.get_owned("file_owned", "ws_a", "usr_a") is not None
    assert store.get_owned("file_owned", "ws_b", "usr_a") is None
    assert store.get_owned("file_owned", "ws_a", "usr_b") is not None


def test_task_input_binding_is_immutable_and_carries_server_ownership() -> None:
    # Given
    binding = TaskInputFile(
        file_id="file_owned",
        file_path="/tmp/owned.pdf",
        filename="owned.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        workspace_id="ws_a",
        uploaded_by_user_id="usr_a",
    )

    # When / Then
    with pytest.raises(ValidationError):
        binding.workspace_id = "ws_b"


def test_workspace_scoped_binding_never_falls_back_to_unowned_file_lookup() -> None:
    store = FileStore()
    store.put(
        UploadedFileRecord(
            file_id="file_owned",
            storage_path="/tmp/owned.pdf",
            filename="owned.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            workspace_id="ws_a",
            uploaded_by_user_id="usr_a",
        )
    )
    orchestrator = object.__new__(TaskOrchestrator)
    orchestrator._file_store = store
    workflow = WorkflowDefinition(
        nodes=[WorkflowNode(id="input_1", type="input/document", config={})],
        connections=[],
    )

    with pytest.raises(ValueError, match="requested_by_user_id is required"):
        orchestrator._resolve_input_bindings(
            workflow,
            ["file_owned"],
            workspace_id="ws_a",
            requested_by_user_id=None,
        )

    with pytest.raises(ValueError, match="找不到檔案"):
        orchestrator._resolve_input_bindings(
            workflow,
            ["file_owned"],
            workspace_id="ws_b",
            requested_by_user_id="usr_a",
        )

    binding = orchestrator._resolve_input_bindings(
        workflow,
        ["file_owned"],
        workspace_id="ws_a",
        requested_by_user_id="usr_a",
    )
    assert binding["input_1"].file_id == "file_owned"
