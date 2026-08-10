from __future__ import annotations

import builtins
from pathlib import Path

import httpx
import pytest

import app.services.adaptor_executor as adaptor_executor_module
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import BinaryRef, NodeOutput
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.adaptor_executor import make_adaptor_node_executor
from app.services.dag_scheduler import DAGNode, NodeExecutionContext
from app.services.sandbox_client import SandboxClient
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits


def _workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/image", config={"file": "$file_0"}),
            WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="ocr_1", target_port="images"),
            WorkflowConnection(source="ocr_1", target="adaptor_1", target_port="input"),
            WorkflowConnection(source="adaptor_1", target="end_1", target_port="input"),
        ],
    )


def _completed_outputs() -> dict[str, NodeOutput]:
    return {
        "input_1": NodeOutput(
            binary=[BinaryRef(data="aGVsbG8=", mime_type="image/png", size_bytes=5)],
            metadata={"filename": "image.png"},
        ),
        "ocr_1": NodeOutput(text="recognized", metadata={"step": "ocr"}),
    }


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(status_code: int, body: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        request=httpx.Request("GET", "http://sandbox-broker.test"),
    )


class _Settings:
    adaptor_sandbox_broker_url = "http://adaptor-sandbox-broker:8080"
    storage_root = "/storage"


class _CaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.health_calls = 0
        self.config_calls = 0
        self.process_calls = 0

    async def health(self) -> dict[str, object]:
        self.health_calls += 1
        return {"status": "ok", "version": "1.0", "runner_reachable": True}

    async def config(self) -> dict[str, object]:
        self.config_calls += 1
        return {
            "engine": "adaptor-sandbox",
            "version": "1.0",
            "schema_version": "v1",
            "policy_digest": POLICY_DIGEST,
            "limits": {"max_code_bytes": 65536},
            "network_policy": "runner-network-none",
        }

    async def process(self, **kwargs: object) -> NodeOutput:
        self.process_calls += 1
        self.calls.append(kwargs)
        return NodeOutput(text="ok", metadata={})

    async def close(self) -> None:
        return None


def _settings_with_storage_root(storage_root: Path):
    return type(
        "_StorageSettings",
        (),
        {
            "adaptor_sandbox_broker_url": "http://adaptor-sandbox-broker:8080",
            "storage_root": str(storage_root),
        },
    )()


class _TrackingOpenFile:
    def __init__(self, handle, *, fail_on_read: bool = False) -> None:
        self._handle = handle
        self.fail_on_read = fail_on_read
        self.read_calls = 0

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return self._handle.__exit__(exc_type, exc, tb)

    def fileno(self) -> int:
        return self._handle.fileno()

    def read(self, *args, **kwargs):
        self.read_calls += 1
        if self.fail_on_read:
            raise AssertionError("read should not be called")
        return self._handle.read(*args, **kwargs)


@pytest.mark.asyncio()
async def test_composite_executor_delegates_non_adaptor_nodes_to_base_executor() -> None:
    calls: list[tuple[str, dict[str, NodeOutput], NodeExecutionContext | None]] = []

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        calls.append((node.node_id, inputs, context))
        return NodeOutput(text="base-result", metadata={"processing_time_ms": 7})

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
    )

    context = NodeExecutionContext(
        run_id="run-1",
        completed_outputs=_completed_outputs(),
    )
    result = await executor(
        DAGNode(
            node_id="ocr_1",
            node_type="engine/ocr",
            config={},
            named_inputs={},
            dependencies=set(),
        ),
        {"images": NodeOutput(text="input")},
        context,
    )

    assert result.text == "base-result"
    assert calls == [("ocr_1", {"images": NodeOutput(text="input")}, context)]


@pytest.mark.asyncio()
async def test_composite_executor_routes_adaptor_with_all_upstream_and_validates_output() -> None:
    transport = _Transport(
        [
            _response(200, {"status": "ok", "version": "1.0", "runner_reachable": True}),
            _response(
                200,
                {
                    "engine": "adaptor-sandbox",
                    "version": "1.0",
                    "schema_version": "v1",
                    "policy_digest": POLICY_DIGEST,
                    "limits": {"max_code_bytes": 65536},
                    "network_policy": "runner-network-none",
                },
            ),
            _response(
                200,
                {
                    "request_id": "req-1",
                    "status": "ok",
                    "result": {
                        "text": "adapted",
                        "binary": [],
                        "structured": {"ok": True},
                        "metadata": {"from": "sandbox"},
                    },
                    "error": None,
                    "metrics": {"wall_time_ms": 12},
                },
            ),
        ]
    )

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )
    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _Settings(),
    )

    result = await executor(
        DAGNode(
            node_id="adaptor_1",
            node_type="processor/adaptor",
            config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
            named_inputs={"input": ["ocr_1"]},
            dependencies={"ocr_1"},
        ),
        {"input": NodeOutput(text="ignored-by-adaptor-route")},
        NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
    )

    assert result.text == "adapted"
    assert result.structured == {"ok": True}
    assert result.metadata["from"] == "sandbox"
    assert result.metadata["processing_time_ms"] == 12

    body = transport.requests[2].read().decode("utf-8")
    assert '"ocr_1"' in body
    assert '"recognized"' in body

    await client.close()


@pytest.mark.asyncio()
async def test_composite_executor_uses_custom_bindings_mode() -> None:
    captured_inputs: dict[str, object] = {}

    class _Client:
        async def health(self) -> dict[str, object]:
            return {"status": "ok", "version": "1.0", "runner_reachable": True}

        async def config(self) -> dict[str, object]:
            return {
                "engine": "adaptor-sandbox",
                "version": "1.0",
                "schema_version": "v1",
                "policy_digest": POLICY_DIGEST,
                "limits": {"max_code_bytes": 65536},
                "network_policy": "runner-network-none",
            }

        async def process(self, **kwargs: object) -> NodeOutput:
            captured_inputs.update(kwargs)
            return NodeOutput(text="bound", metadata={})

        async def close(self) -> None:
            return None

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: _Client(),
        settings_getter=lambda: _Settings(),
    )

    await executor(
        DAGNode(
            node_id="adaptor_1",
            node_type="processor/adaptor",
            config={
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "input_mode": "custom_bindings",
                "input_bindings": [{"name": "doc", "selector": ["ocr_1", "text"]}],
            },
            named_inputs={"input": ["ocr_1"]},
            dependencies={"ocr_1"},
        ),
        {},
        NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
    )

    sandbox_inputs = captured_inputs["inputs"]
    assert isinstance(sandbox_inputs, dict)
    assert list(sandbox_inputs) == ["doc"]
    assert sandbox_inputs["doc"].text == "recognized"


@pytest.mark.asyncio()
async def test_composite_executor_inlines_binary_ref_within_storage_root(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    payload_path = storage_root / "tasks" / "task-1" / "image.png"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"hello")
    original_output = NodeOutput(
        binary=[BinaryRef(ref="tasks/task-1/image.png", mime_type="image/png", size_bytes=5)],
        metadata={"filename": "image.png"},
    )
    completed_outputs = {
        **_completed_outputs(),
        "input_1": original_output,
    }
    client = _CaptureClient()

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    await executor(
        DAGNode(
            node_id="adaptor_1",
            node_type="processor/adaptor",
            config={
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "input_mode": "custom_bindings",
                "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
            },
            named_inputs={"input": ["input_1"]},
            dependencies={"input_1"},
        ),
        {},
        NodeExecutionContext(run_id="run-1", completed_outputs=completed_outputs),
    )

    sent_inputs = client.calls[0]["inputs"]
    assert isinstance(sent_inputs, dict)
    assert sent_inputs["image"].binary[0].data == "aGVsbG8="
    assert sent_inputs["image"].binary[0].ref == ""
    assert completed_outputs["input_1"].binary[0].ref == "tasks/task-1/image.png"
    assert completed_outputs["input_1"].binary[0].data is None


@pytest.mark.asyncio()
async def test_composite_executor_inlines_binary_ref_via_to_thread_and_one_open_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    payload_path = storage_root / "tasks" / "task-1" / "image.png"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"hello")
    client = _CaptureClient()
    to_thread_calls: list[tuple[object, tuple[object, ...]]] = []
    tracking_files: list[_TrackingOpenFile] = []
    original_open = builtins.open

    async def _fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append((func, args))
        return func(*args, **kwargs)

    def _tracking_open(*args, **kwargs):
        wrapped = _TrackingOpenFile(original_open(*args, **kwargs))
        tracking_files.append(wrapped)
        return wrapped

    monkeypatch.setattr(adaptor_executor_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(builtins, "open", _tracking_open)

    executor = make_adaptor_node_executor(
        base_executor=lambda *args, **kwargs: pytest.fail("base executor should not be used"),
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    await executor(
        DAGNode(
            node_id="adaptor_1",
            node_type="processor/adaptor",
            config={
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "input_mode": "custom_bindings",
                "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
            },
            named_inputs={"input": ["input_1"]},
            dependencies={"input_1"},
        ),
        {},
        NodeExecutionContext(
            run_id="run-1",
            completed_outputs={
                **_completed_outputs(),
                "input_1": NodeOutput(
                    binary=[
                        BinaryRef(
                            ref="tasks/task-1/image.png",
                            mime_type="image/png",
                            size_bytes=5,
                        )
                    ]
                ),
            },
        ),
    )

    assert len(to_thread_calls) == 1
    assert len(tracking_files) == 1
    assert tracking_files[0].read_calls == 1
    assert client.process_calls == 1


@pytest.mark.asyncio()
async def test_composite_executor_rejects_oversize_binary_ref_before_read_and_broker_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    payload_path = storage_root / "tasks" / "task-1" / "oversize.bin"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"x" * (SandboxLimits().max_binary_item_bytes + 1))
    client = _CaptureClient()
    to_thread_calls: list[tuple[object, tuple[object, ...]]] = []
    tracking_files: list[_TrackingOpenFile] = []
    original_open = builtins.open

    async def _fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append((func, args))
        return func(*args, **kwargs)

    def _tracking_open(*args, **kwargs):
        wrapped = _TrackingOpenFile(original_open(*args, **kwargs), fail_on_read=True)
        tracking_files.append(wrapped)
        return wrapped

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    monkeypatch.setattr(adaptor_executor_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(builtins, "open", _tracking_open)

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
                },
                named_inputs={"input": ["input_1"]},
                dependencies={"input_1"},
            ),
            {},
            NodeExecutionContext(
                run_id="run-1",
                completed_outputs={
                    **_completed_outputs(),
                    "input_1": NodeOutput(
                        binary=[
                            BinaryRef(
                                ref="tasks/task-1/oversize.bin",
                                mime_type="application/octet-stream",
                                size_bytes=SandboxLimits().max_binary_item_bytes + 1,
                            )
                        ]
                    ),
                },
            ),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert exc_info.value.message == "Sandbox request is invalid"
    assert len(to_thread_calls) == 1
    assert len(tracking_files) == 1
    assert tracking_files[0].read_calls == 0
    assert client.health_calls == 0
    assert client.config_calls == 0
    assert client.process_calls == 0


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "ref_value",
    [
        "../escape.png",
        "/tmp/outside.png",
    ],
)
async def test_composite_executor_rejects_binary_refs_outside_storage_root_without_leaking_paths(
    tmp_path: Path,
    ref_value: str,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    completed_outputs = {
        **_completed_outputs(),
        "input_1": NodeOutput(
            binary=[BinaryRef(ref=ref_value, mime_type="image/png", size_bytes=5)],
            metadata={"filename": "image.png"},
        ),
    }
    client = _CaptureClient()

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
                },
                named_inputs={"input": ["input_1"]},
                dependencies={"input_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=completed_outputs),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert exc_info.value.message == "Sandbox request is invalid"
    assert ref_value not in str(exc_info.value)
    assert str(storage_root) not in str(exc_info.value)
    assert client.calls == []


@pytest.mark.asyncio()
async def test_composite_executor_rejects_symlink_escape_without_leaking_paths(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"hello")
    link_path = storage_root / "tasks" / "escape.png"
    link_path.parent.mkdir(parents=True)
    link_path.symlink_to(outside)
    client = _CaptureClient()

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
                },
                named_inputs={"input": ["input_1"]},
                dependencies={"input_1"},
            ),
            {},
            NodeExecutionContext(
                run_id="run-1",
                completed_outputs={
                    **_completed_outputs(),
                    "input_1": NodeOutput(
                        binary=[
                            BinaryRef(ref="tasks/escape.png", mime_type="image/png", size_bytes=5)
                        ],
                        metadata={"filename": "image.png"},
                    ),
                },
            ),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert exc_info.value.message == "Sandbox request is invalid"
    assert "escape.png" not in str(exc_info.value)
    assert str(outside) not in str(exc_info.value)
    assert client.calls == []


@pytest.mark.asyncio()
async def test_composite_executor_rejects_missing_binary_ref_without_leaking_paths(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    client = _CaptureClient()

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
                },
                named_inputs={"input": ["input_1"]},
                dependencies={"input_1"},
            ),
            {},
            NodeExecutionContext(
                run_id="run-1",
                completed_outputs={
                    **_completed_outputs(),
                    "input_1": NodeOutput(
                        binary=[
                            BinaryRef(
                                ref="tasks/task-1/missing.png",
                                mime_type="image/png",
                                size_bytes=5,
                            )
                        ],
                        metadata={"filename": "image.png"},
                    ),
                },
            ),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert exc_info.value.message == "Sandbox request is invalid"
    assert "missing.png" not in str(exc_info.value)
    assert str(storage_root) not in str(exc_info.value)
    assert client.calls == []


@pytest.mark.asyncio()
async def test_composite_executor_preserves_serializer_limit_validation_for_inlined_refs(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    payload_path = storage_root / "tasks" / "task-1" / "image.png"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"payload")
    transport = _Transport(
        [
            _response(200, {"status": "ok", "version": "1.0", "runner_reachable": True}),
            _response(
                200,
                {
                    "engine": "adaptor-sandbox",
                    "version": "1.0",
                    "schema_version": "v1",
                    "policy_digest": POLICY_DIGEST,
                    "limits": {"max_code_bytes": 65536},
                    "network_policy": "runner-network-none",
                },
            ),
        ]
    )

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _settings_with_storage_root(storage_root),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "image", "selector": ["input_1", "binary"]}],
                },
                named_inputs={"input": ["input_1"]},
                dependencies={"input_1"},
            ),
            {},
            NodeExecutionContext(
                run_id="run-1",
                completed_outputs={
                    **_completed_outputs(),
                    "input_1": NodeOutput(
                        binary=[
                            BinaryRef(
                                ref="tasks/task-1/image.png",
                                mime_type="image/png",
                                size_bytes=999,
                            )
                        ]
                    ),
                },
            ),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert exc_info.value.message == "Sandbox request is invalid"
    assert [request.url.path for request in transport.requests] == ["/health", "/config"]
    await client.close()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("health_payload", "config_payload", "expected_code", "expected_message"),
    [
        (
            {"status": "ok", "version": "1.0", "runner_reachable": False},
            None,
            ErrorCode.ENGINE_UNREACHABLE,
            "Sandbox broker is unreachable",
        ),
        (
            {"status": "ok", "version": "1.0", "runner_reachable": True},
            {
                "engine": "adaptor-sandbox",
                "version": "1.0",
                "schema_version": "v1",
                "policy_digest": "wrong-digest",
                "limits": {"max_code_bytes": 65536},
                "network_policy": "runner-network-none",
            },
            ErrorCode.ENGINE_INVALID_RESPONSE,
            "Sandbox broker returned an invalid config response",
        ),
        (
            {"status": "ok", "version": "1.0", "runner_reachable": True},
            {
                "engine": "adaptor-sandbox",
                "version": "1.0",
                "schema_version": "v1",
                "policy_digest": POLICY_DIGEST,
                "limits": {"max_code_bytes": 65536},
                "network_policy": "unexpected-network",
            },
            ErrorCode.ENGINE_INVALID_RESPONSE,
            "Sandbox broker returned an invalid config response",
        ),
    ],
)
async def test_composite_executor_fails_closed_on_health_or_policy_drift(
    health_payload: dict[str, object],
    config_payload: dict[str, object] | None,
    expected_code: ErrorCode,
    expected_message: str,
) -> None:
    responses: list[httpx.Response] = [_response(200, health_payload)]
    if config_payload is not None:
        responses.append(_response(200, config_payload))
    transport = _Transport(responses)

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )
    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _Settings(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
                named_inputs={"input": ["ocr_1"]},
                dependencies={"ocr_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
        )

    assert exc_info.value.error_code == expected_code
    assert exc_info.value.message == expected_message
    await client.close()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            _response(
                503,
                {
                    "request_id": "req-1",
                    "status": "error",
                    "result": None,
                    "error": {"kind": "queue_full", "message": "busy"},
                    "metrics": {},
                },
            ),
            ErrorCode.ENGINE_RATE_LIMITED,
        ),
        (
            httpx.TimeoutException("timeout"),
            ErrorCode.ENGINE_TIMEOUT,
        ),
    ],
)
async def test_composite_executor_preserves_retryable_engine_errors(
    response: httpx.Response | Exception,
    expected_code: ErrorCode,
) -> None:
    transport = _Transport(
        [
            _response(200, {"status": "ok", "version": "1.0", "runner_reachable": True}),
            _response(
                200,
                {
                    "engine": "adaptor-sandbox",
                    "version": "1.0",
                    "schema_version": "v1",
                    "policy_digest": POLICY_DIGEST,
                    "limits": {"max_code_bytes": 65536},
                    "network_policy": "runner-network-none",
                },
            ),
            response,
        ]
    )

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    client = SandboxClient(
        base_url="http://sandbox-broker:8080",
        client=httpx.AsyncClient(transport=transport),
    )
    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: client,
        settings_getter=lambda: _Settings(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
                named_inputs={"input": ["ocr_1"]},
                dependencies={"ocr_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
        )

    assert exc_info.value.error_code == expected_code
    await client.close()


@pytest.mark.asyncio()
async def test_composite_executor_rejects_invalid_code_without_leaking_runtime_details() -> None:
    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=lambda: SandboxClient(base_url="http://sandbox-broker:8080"),
        settings_getter=lambda: _Settings(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={"code": "   ", "input_mode": "all_upstream"},
                named_inputs={"input": ["ocr_1"]},
                dependencies={"ocr_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert "recognized" not in str(exc_info.value)


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "broker_url",
    [
        "https://adaptor-sandbox-broker:8080",
        "http://user:pass@adaptor-sandbox-broker:8080",
        "http://adaptor-sandbox-broker:8081",
        "http://example.com:8080",
        "http://adaptor-sandbox-broker:8080/path",
        "http://adaptor-sandbox-broker:8080/?q=1",
        "http://adaptor-sandbox-broker:8080/#frag",
    ],
)
async def test_composite_executor_rejects_noncanonical_broker_url_before_client_creation(
    broker_url: str,
) -> None:
    created = False

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    def _factory() -> SandboxClient:
        nonlocal created
        created = True
        raise AssertionError("sandbox client should not be created")

    class _InvalidSettings:
        adaptor_sandbox_broker_url = broker_url

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=_factory,
        settings_getter=lambda: _InvalidSettings(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
                named_inputs={"input": ["ocr_1"]},
                dependencies={"ocr_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
        )

    assert exc_info.value.error_code == ErrorCode.ENGINE_UNREACHABLE
    assert broker_url not in str(exc_info.value)
    assert created is False


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "config",
    [
        {
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "input_mode": 7,
        },
        {
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "input_mode": "   ",
        },
        {
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "input_mode": "sideways",
        },
        {
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "input_bindings": {"name": "doc"},
        },
        {
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "input_mode": "custom_bindings",
        },
    ],
)
async def test_composite_executor_rejects_malformed_runtime_input_config_without_client_creation(
    config: dict[str, object],
) -> None:
    sandbox_factory_calls: list[str] = []

    async def _base_executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
        context: NodeExecutionContext | None = None,
    ) -> NodeOutput:
        _ = (node, inputs, context)
        raise AssertionError("adaptor node must not use base executor")

    def _factory() -> SandboxClient:
        sandbox_factory_calls.append("called")
        raise AssertionError("sandbox client should not be created for malformed config")

    executor = make_adaptor_node_executor(
        base_executor=_base_executor,
        definition_resolver=lambda _run_id: _workflow_definition(),
        sandbox_client_factory=_factory,
        settings_getter=lambda: _Settings(),
    )

    with pytest.raises(EngineError) as exc_info:
        await executor(
            DAGNode(
                node_id="adaptor_1",
                node_type="processor/adaptor",
                config=config,
                named_inputs={"input": ["ocr_1"]},
                dependencies={"ocr_1"},
            ),
            {},
            NodeExecutionContext(run_id="run-1", completed_outputs=_completed_outputs()),
        )

    assert exc_info.value.error_code == ErrorCode.INVALID_NODE_CONFIG
    assert sandbox_factory_calls == []
