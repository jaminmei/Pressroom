from __future__ import annotations

import types
from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    RUNNER = "runner"
    VIEWER = "viewer"


_CAPABILITIES_RAW: dict[WorkspaceRole, frozenset[str]] = {
    WorkspaceRole.OWNER: frozenset(
        {
            "workspace.view",
            "workspace.update_settings",
            "workspace.delete",
            "workspace.transfer_owner",
            "workspace.manage_members",
            "workflow.view",
            "workflow.edit_draft",
            "workflow.publish",
            "workflow.run",
            "file.view",
            "file.upload",
            "file.delete",
            "dataset.view",
            "dataset.create",
            "document.upload",
            "ground_truth.manage",
            "run.view",
            "run.cancel",
            "comparison.refresh",
            "provider.view",
            "provider.manage",
            "provider.use",
            "api_key.manage",
            "api_usage.view",
        }
    ),
    WorkspaceRole.ADMIN: frozenset(
        {
            "workspace.view",
            "workspace.update_settings",
            "workspace.manage_members",
            "workflow.view",
            "workflow.edit_draft",
            "workflow.publish",
            "workflow.run",
            "file.view",
            "file.upload",
            "file.delete",
            "dataset.view",
            "dataset.create",
            "document.upload",
            "ground_truth.manage",
            "run.view",
            "run.cancel",
            "comparison.refresh",
            "provider.view",
            "provider.manage",
            "provider.use",
            "api_key.manage",
            "api_usage.view",
        }
    ),
    WorkspaceRole.EDITOR: frozenset(
        {
            "workspace.view",
            "workflow.view",
            "workflow.edit_draft",
            "workflow.run",
            "file.view",
            "file.upload",
            "file.delete",
            "dataset.view",
            "dataset.create",
            "document.upload",
            "ground_truth.manage",
            "run.view",
            "run.cancel",
            "comparison.refresh",
            "provider.view",
            "provider.use",
        }
    ),
    WorkspaceRole.RUNNER: frozenset(
        {
            "workspace.view",
            "workflow.view",
            "workflow.run",
            "file.view",
            "file.upload",
            "dataset.view",
            "run.view",
            "run.cancel",
            "comparison.refresh",
            "provider.view",
            "provider.use",
        }
    ),
    WorkspaceRole.VIEWER: frozenset(
        {
            "workspace.view",
            "workflow.view",
            "file.view",
            "dataset.view",
            "run.view",
            "provider.view",
        }
    ),
}

# This mapping is the authoritative public capability set. Future DB-backed
# overrides must resolve to a capability set before authorization checks.
CAPABILITIES = types.MappingProxyType(_CAPABILITIES_RAW)

assert set(CAPABILITIES) == set(WorkspaceRole), "every WorkspaceRole must have a CAPABILITIES entry"
