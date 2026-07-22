from __future__ import annotations

import pytest

from tests.integration.workspace_api_support import WorkspaceApiHarness


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_workspace_name_rejects_empty_or_too_long_input(
    workspace_api_harness: WorkspaceApiHarness, name: str
) -> None:
    owner = workspace_api_harness.register_user("name-owner@example.com", "Owner")

    response = owner.client.post("/api/workspaces", json={"name": name})

    assert response.status_code == 422


def test_workspace_name_is_trimmed_and_duplicates_are_allowed(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("name-trim@example.com", "Owner")

    first = owner.client.post("/api/workspaces", json={"name": "  Workspace  "})
    second = owner.client.post("/api/workspaces", json={"name": "Workspace"})
    updated = owner.client.patch(
        f"/api/workspaces/{first.json()['id']}", json={"name": "  Renamed  "}
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["name"] == "Workspace"
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"


def test_workspace_name_accepts_one_hundred_unicode_code_points(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("name-unicode@example.com", "Owner")

    response = owner.client.post("/api/workspaces", json={"name": "名" * 100})

    assert response.status_code == 201
