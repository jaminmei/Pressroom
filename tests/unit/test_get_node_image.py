from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.execution import BinaryRef, NodeOutput
from tests._api_workspace_contract import (
    TEST_WORKSPACE_ID,
    install_authenticated_workspace,
    remove_authenticated_workspace,
)


def _stub_node_output(
    output: Any,
    *,
    node_type: str = "test_node",
    events: list[Any] | None = None,
) -> None:
    app.state.running_tasks = {
        "task-1": SimpleNamespace(run_id="task-1", workspace_id=TEST_WORKSPACE_ID)
    }
    app.state.event_store = SimpleNamespace(get_events=lambda _run_id: events or [])

    def _fake_node_output_from_events(_run_id: str, _node_id: str, _event_store: Any):
        return output, "completed", None, node_type

    import app.api.tasks as tasks_module

    tasks_module._node_output_from_events = _fake_node_output_from_events


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    install_authenticated_workspace(app, monkeypatch)
    try:
        yield TestClient(app)
    finally:
        app.state.running_tasks = {}
        remove_authenticated_workspace(app)


def test_serves_image_from_inline_base64_data(client: TestClient) -> None:
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-png-bytes").decode("ascii")
    output = NodeOutput(
        binary=[BinaryRef(ref="", data=payload, mime_type="image/png", size_bytes=len(payload))]
    )
    _stub_node_output(output)

    response = client.get("/api/tasks/task-1/nodes/node-1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_serves_image_from_ref_path_fallback(client: TestClient, tmp_path) -> None:
    image_file = tmp_path / "result.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nfile-based-bytes")
    output = NodeOutput(
        binary=[BinaryRef(ref=str(image_file), data=None, mime_type="image/png", size_bytes=20)]
    )
    _stub_node_output(output)

    response = client.get("/api/tasks/task-1/nodes/node-1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_backward_compat_index_zero_implicit(client: TestClient, tmp_path) -> None:
    image_file = tmp_path / "result.png"
    image_file.write_bytes(b"\x89PNG legacy bytes")
    output = NodeOutput(
        binary=[BinaryRef(ref=str(image_file), data=None, mime_type="image/png", size_bytes=15)]
    )
    _stub_node_output(output)

    response_no_index = client.get("/api/tasks/task-1/nodes/node-1/image")
    response_index_zero = client.get("/api/tasks/task-1/nodes/node-1/image?index=0")

    assert response_no_index.status_code == 200
    assert response_index_zero.status_code == 200
    assert response_no_index.content == response_index_zero.content


def test_serves_specific_entry_by_index(client: TestClient) -> None:
    payload_a = base64.b64encode(b"image-a-bytes").decode("ascii")
    payload_b = base64.b64encode(b"image-b-bytes").decode("ascii")
    payload_c = base64.b64encode(b"image-c-bytes").decode("ascii")
    output = NodeOutput(
        binary=[
            BinaryRef(ref="", data=payload_a, mime_type="image/png"),
            BinaryRef(ref="", data=payload_b, mime_type="image/jpeg"),
            BinaryRef(ref="", data=payload_c, mime_type="image/png"),
        ]
    )
    _stub_node_output(output)

    response_0 = client.get("/api/tasks/task-1/nodes/node-1/image?index=0")
    response_1 = client.get("/api/tasks/task-1/nodes/node-1/image?index=1")
    response_2 = client.get("/api/tasks/task-1/nodes/node-1/image?index=2")

    assert response_0.status_code == 200
    assert response_0.content == b"image-a-bytes"
    assert response_1.status_code == 200
    assert response_1.headers["content-type"] == "image/jpeg"
    assert response_1.content == b"image-b-bytes"
    assert response_2.status_code == 200
    assert response_2.content == b"image-c-bytes"


def test_index_out_of_range_returns_404(client: TestClient) -> None:
    output = NodeOutput(
        binary=[
            BinaryRef(ref="", data=base64.b64encode(b"x").decode("ascii"), mime_type="image/png"),
            BinaryRef(ref="", data=base64.b64encode(b"y").decode("ascii"), mime_type="image/png"),
            BinaryRef(ref="", data=base64.b64encode(b"z").decode("ascii"), mime_type="image/png"),
        ]
    )
    _stub_node_output(output)

    response = client.get("/api/tasks/task-1/nodes/node-1/image?index=5")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "INDEX_OUT_OF_RANGE"


def test_entry_with_neither_data_nor_ref_returns_404(client: TestClient) -> None:
    output = NodeOutput(
        binary=[
            BinaryRef(ref="", data=None, mime_type="image/png"),
        ]
    )
    _stub_node_output(output)

    response = client.get("/api/tasks/task-1/nodes/node-1/image")

    assert response.status_code == 404


def test_empty_binary_list_returns_404(client: TestClient) -> None:
    output = NodeOutput(binary=[])
    _stub_node_output(output)

    response = client.get("/api/tasks/task-1/nodes/node-1/image")

    assert response.status_code == 404


def test_layout_result_serves_upstream_source_image(client: TestClient) -> None:
    source_bytes = b"upstream-layout-source"
    source_output = NodeOutput(
        binary=[
            BinaryRef(
                ref="",
                data=base64.b64encode(source_bytes).decode("ascii"),
                mime_type="image/png",
                size_bytes=len(source_bytes),
            )
        ]
    )
    layout_output = NodeOutput(
        structured={
            "kind": "layout_regions",
            "elements": [],
            "total_regions": 0,
        }
    )
    events = [
        SimpleNamespace(
            node_id="input-1",
            event_type="completed",
            output=source_output,
            resolved_inputs={},
        ),
        SimpleNamespace(
            node_id="layout-1",
            event_type="started",
            output=None,
            resolved_inputs={
                "image": SimpleNamespace(source_node_id="input-1"),
            },
        ),
    ]
    _stub_node_output(
        layout_output,
        node_type="processor/layout_detection",
        events=events,
    )

    response = client.get("/api/tasks/task-1/nodes/layout-1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == source_bytes
