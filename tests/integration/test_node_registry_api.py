from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.usefixtures("authenticated_workspace_contract")


@pytest.mark.anyio
async def test_get_node_registry_returns_expected_catalog() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/nodes/registry")

    assert response.status_code == 200
    body = response.json()

    assert body["version"] == "1.0.0"
    category_ids = {item["category_id"] for item in body["categories"]}
    assert category_ids == {"input", "processor", "engine", "end"}

    nodes = {node["node_type"]: node for node in body["nodes"]}
    assert "engine/ocr" in nodes
    assert "engine/model" in nodes
    assert "engine/text" in nodes
    assert "engine/markitdown" in nodes
    assert "text/html" in nodes["engine/text"]["input_types"]
    assert nodes["end/final"]["max_outputs"] == 0
