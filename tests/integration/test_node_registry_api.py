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
    assert "processor/adaptor" in nodes
    assert "processor/iteration" in nodes
    assert "text/html" in nodes["engine/text"]["input_types"]
    assert nodes["end/final"]["max_outputs"] == 0
    assert nodes["processor/adaptor"]["config_schema"]["required"] == ["code"]
    assert nodes["processor/adaptor"]["input_ports"][0]["accepted_types"] == ["*/*"]
    adaptor_items = nodes["processor/adaptor"]["config_schema"]["properties"]["input_bindings"][
        "items"
    ]
    assert adaptor_items["type"] == "object"
    assert adaptor_items["required"] == ["name", "selector"]
    assert adaptor_items["properties"]["selector"]["minItems"] == 2
    assert nodes["processor/adaptor"]["output_types"] == ["application/x-adaptor-output"]
    assert nodes["processor/iteration"]["config_schema"]["required"] == [
        "engine_node_type",
        "engine_config",
        "iterate_over",
        "item_input_port",
        "mode",
        "max_concurrency",
        "error_handling",
    ]
    assert (
        nodes["processor/iteration"]["config_schema"]["properties"]["engine_config"]["type"]
        == "object"
    )
    assert nodes["processor/iteration"]["config_schema"]["properties"]["max_concurrency"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 5,
    }
    assert nodes["processor/iteration"]["input_ports"][0]["accepted_types"] == ["*/*"]
    assert nodes["processor/iteration"]["input_ports"][0]["max_connections"] == 1
    assert nodes["processor/iteration"]["output_types"] == ["application/x-iteration-output"]
