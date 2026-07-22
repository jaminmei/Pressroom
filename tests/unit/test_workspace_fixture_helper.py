from __future__ import annotations

import os

from tests._workspace_fixture import disable_rbac, enable_rbac


def test_workspace_fixture_rbac_helpers_toggle_environment(monkeypatch) -> None:
    enable_rbac(monkeypatch)
    assert os.environ["WORKSPACE_RBAC_ENFORCED"] == "true"

    disable_rbac(monkeypatch)
    assert os.environ["WORKSPACE_RBAC_ENFORCED"] == "false"
