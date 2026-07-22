def _require_workspace_filter(workspace_id: str | None) -> str:
    if workspace_id is None:
        raise RuntimeError("workspace_id required for repository filter")
    return workspace_id
