from __future__ import annotations

from app.config import Settings, get_settings


def workspace_rbac_enforced(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).workspace_rbac_enforced)
