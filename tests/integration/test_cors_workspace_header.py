from starlette.testclient import TestClient

from app.main import app


def test_patch_preflight_allows_workspace_header() -> None:
    # Given
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "X-Workspace-Id",
    }

    # When
    client = TestClient(app)
    try:
        response = client.options("/api/workspaces/current", headers=headers)
    finally:
        client.close()

    # Then
    assert response.status_code == 200
    assert "x-workspace-id" in response.headers["access-control-allow-headers"].lower()
