from __future__ import annotations

import pytest

from app.models.task import TaskInputFile
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.dag_scheduler import DAGRunResult
from app.services.durable_workflow_execution import DurableWorkflowExecutionService


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(self, workflow: WorkflowDefinition, **kwargs: object) -> DAGRunResult:
        self.calls.append({"workflow": workflow, **kwargs})
        return DAGRunResult(completed={}, failed={}, skipped=set())


class _ProviderStore:
    def get_for_runtime(self, provider_id: str, workspace_id: str) -> object | None:
        _ = (provider_id, workspace_id)
        return None


class _EngineClient:
    pass


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="adaptor_1",
                type="processor/adaptor",
                config={"code": "def main(inputs):\n    return {'text': 'ok'}"},
            ),
        ],
        connections=[WorkflowConnection(source="input_1", target="adaptor_1", target_port="input")],
    )


def _engine_only_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(id="ocr_1", type="engine/ocr", config={}),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="ocr_1", target_port="input"),
            WorkflowConnection(source="ocr_1", target="end_1", target_port="input"),
        ],
    )


def _iteration_workflow(
    inner_type: str, inner_config: dict[str, object] | None = None
) -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input_1", type="input/text", config={"file": "$file_0"}),
            WorkflowNode(
                id="iter_1",
                type="processor/iteration",
                config={
                    "engine_node_type": inner_type,
                    "engine_config": inner_config or {},
                    "iterate_over": "binary",
                    "item_input_port": "image",
                    "mode": "sequential",
                    "max_concurrency": 5,
                    "error_handling": "terminate",
                },
            ),
            WorkflowNode(id="end_1", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="input_1", target="iter_1", target_port="input"),
            WorkflowConnection(source="iter_1", target="end_1", target_port="input"),
        ],
    )


async def _run_service(service: DurableWorkflowExecutionService, scheduler: _Scheduler) -> None:
    await service.execute(
        _workflow(),
        task_id="run-1",
        input_bindings={
            "input_1": TaskInputFile(
                file_path="/tmp/input.txt",
                filename="input.txt",
                mime_type="text/plain",
            )
        },
        workspace_id="ws-1",
    )
    assert scheduler.calls, "scheduler.run should be invoked"


def test_durable_workflow_service_builds_composite_executor_without_eager_sandbox_client(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    created_engine_clients: list[object] = []
    make_node_executor_calls: list[tuple[object, object, object]] = []
    composite_calls: list[tuple[object, object, object, object]] = []

    def _fake_make_node_executor(
        engine_client: object,
        auth_resolver: object,
        provider_resolver: object,
    ):
        created_engine_clients.append(engine_client)
        make_node_executor_calls.append((engine_client, auth_resolver, provider_resolver))

        async def _executor(node, inputs, context=None):
            _ = (node, inputs, context)
            raise AssertionError("base executor should not run in this test")

        return _executor

    def _fake_make_adaptor_node_executor(
        *,
        base_executor,
        definition_resolver,
        sandbox_client_factory,
        settings_getter=None,
    ):
        composite_calls.append(
            (base_executor, definition_resolver, sandbox_client_factory, settings_getter)
        )

        async def _executor(node, inputs, context=None):
            _ = (node, inputs, context)
            return None

        return _executor

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.make_node_executor",
        _fake_make_node_executor,
    )
    monkeypatch.setattr(
        "app.services.durable_workflow_execution.make_adaptor_node_executor",
        _fake_make_adaptor_node_executor,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=_EngineClient(),
        auth_resolver=object(),
        provider_store=_ProviderStore(),
    )

    import asyncio

    asyncio.run(_run_service(service, scheduler))

    assert len(make_node_executor_calls) == 1
    assert len(composite_calls) == 1
    assert scheduler.calls[0]["node_executor"] is not None


def test_durable_workflow_service_wraps_injected_executor_with_composite_factory(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    composite_calls: list[object] = []

    async def _injected_executor(node, inputs, context=None):
        _ = (node, inputs, context)
        return None

    def _fake_make_adaptor_node_executor(
        *,
        base_executor,
        definition_resolver,
        sandbox_client_factory,
        settings_getter=None,
    ):
        composite_calls.append(base_executor)

        async def _executor(node, inputs, context=None):
            return await base_executor(node, inputs, context)

        return _executor

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.make_adaptor_node_executor",
        _fake_make_adaptor_node_executor,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=None,
        auth_resolver=object(),
        provider_store=_ProviderStore(),
    )

    import asyncio

    asyncio.run(
        service.execute(
            _workflow(),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
            node_executor=_injected_executor,
        )
    )

    assert composite_calls == [_injected_executor]


def test_durable_workflow_service_closes_runtime_resources_on_success(monkeypatch) -> None:
    scheduler = _Scheduler()
    cleanup_calls: list[str] = []

    class _Runtime:
        async def executor(self, node, inputs, context=None):
            _ = (node, inputs, context)
            return DAGRunResult(completed={}, failed={}, skipped=set())

        async def aclose(self) -> None:
            cleanup_calls.append("closed")

    def _fake_build_runtime(**kwargs):
        _ = kwargs
        return _Runtime()

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_adaptor_executor_runtime",
        _fake_build_runtime,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=None,
        auth_resolver=None,
        provider_store=None,
    )

    import asyncio

    asyncio.run(
        service.execute(
            _workflow(),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
            node_executor=lambda *_args, **_kwargs: None,
        )
    )

    assert cleanup_calls == ["closed"]


def test_durable_workflow_service_closes_runtime_resources_on_exception(monkeypatch) -> None:
    cleanup_calls: list[str] = []

    class _FailingScheduler:
        async def run(self, workflow, **kwargs):
            _ = (workflow, kwargs)
            raise RuntimeError("boom")

    class _Runtime:
        async def executor(self, node, inputs, context=None):
            _ = (node, inputs, context)
            return None

        async def aclose(self) -> None:
            cleanup_calls.append("closed")

    def _fake_build_runtime(**kwargs):
        _ = kwargs
        return _Runtime()

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_adaptor_executor_runtime",
        _fake_build_runtime,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=_FailingScheduler(),
        engine_client=None,
        auth_resolver=None,
        provider_store=None,
    )

    import asyncio

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            service.execute(
                _workflow(),
                task_id="run-1",
                input_bindings={
                    "input_1": TaskInputFile(
                        file_path="/tmp/input.txt",
                        filename="input.txt",
                        mime_type="text/plain",
                    )
                },
                workspace_id="ws-1",
                node_executor=lambda *_args, **_kwargs: None,
            )
        )

    assert cleanup_calls == ["closed"]


def test_durable_workflow_service_skips_adaptor_runtime_for_engine_only_workflow(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    settings_calls: list[str] = []
    runtime_builder_calls: list[str] = []
    close_calls: list[str] = []

    async def _base_executor(node, inputs, context=None):
        _ = (node, inputs, context)
        return None

    def _fake_make_node_executor(*args, **kwargs):
        _ = (args, kwargs)
        return _base_executor

    def _explode_settings():
        settings_calls.append("called")
        raise AssertionError("get_settings should not be consulted for engine-only workflows")

    def _explode_build_runtime(**kwargs):
        _ = kwargs
        runtime_builder_calls.append("called")
        raise AssertionError("adaptor runtime should not be built for engine-only workflows")

    class _ExplodingSandboxClient:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)
            raise AssertionError(
                "SandboxClient should not be constructed for engine-only workflows"
            )

        async def close(self) -> None:
            close_calls.append("closed")

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.make_node_executor",
        _fake_make_node_executor,
    )
    monkeypatch.setattr("app.services.durable_workflow_execution.get_settings", _explode_settings)
    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_adaptor_executor_runtime",
        _explode_build_runtime,
    )
    monkeypatch.setattr(
        "app.services.durable_workflow_execution.SandboxClient",
        _ExplodingSandboxClient,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=_EngineClient(),
        auth_resolver=object(),
        provider_store=_ProviderStore(),
    )

    import asyncio

    result = asyncio.run(
        service.execute(
            _engine_only_workflow(),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
        )
    )

    assert result == DAGRunResult(completed={}, failed={}, skipped=set())
    assert len(scheduler.calls) == 1
    assert scheduler.calls[0]["node_executor"] is _base_executor
    assert settings_calls == []
    assert runtime_builder_calls == []
    assert close_calls == []


def test_durable_workflow_service_keeps_injected_executor_plain_for_engine_only_workflow(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    runtime_builder_calls: list[str] = []

    async def _injected_executor(node, inputs, context=None):
        _ = (node, inputs, context)
        return None

    def _explode_build_runtime(**kwargs):
        _ = kwargs
        runtime_builder_calls.append("called")
        raise AssertionError("adaptor runtime should not be built for engine-only workflows")

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_adaptor_executor_runtime",
        _explode_build_runtime,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=None,
        auth_resolver=object(),
        provider_store=_ProviderStore(),
    )

    import asyncio

    asyncio.run(
        service.execute(
            _engine_only_workflow(),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
            node_executor=_injected_executor,
        )
    )

    assert len(scheduler.calls) == 1
    assert scheduler.calls[0]["node_executor"] is _injected_executor
    assert runtime_builder_calls == []


def test_durable_workflow_service_builds_composite_runtime_for_iteration_with_inner_adaptor(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    build_calls: list[dict[str, object]] = []

    class _Runtime:
        async def executor(self, node, inputs, context=None):
            _ = (node, inputs, context)
            return None

        async def aclose(self) -> None:
            return None

    def _fake_build_runtime(**kwargs):
        build_calls.append(kwargs)
        return _Runtime()

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_composite_executor_runtime",
        _fake_build_runtime,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=None,
        auth_resolver=None,
        provider_store=None,
    )

    import asyncio

    asyncio.run(
        service.execute(
            _iteration_workflow(
                "processor/adaptor",
                {
                    "code": "def main(inputs):\n    return {'text': 'ok'}",
                    "input_mode": "custom_bindings",
                    "input_bindings": [{"name": "item", "selector": ["iter_1", "item"]}],
                },
            ),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
            node_executor=lambda *_args, **_kwargs: None,
        )
    )

    assert len(build_calls) == 1


def test_durable_workflow_service_skips_sandbox_runtime_for_iteration_without_inner_adaptor(
    monkeypatch,
) -> None:
    scheduler = _Scheduler()
    build_calls: list[dict[str, object]] = []

    class _Runtime:
        async def executor(self, node, inputs, context=None):
            _ = (node, inputs, context)
            return None

        async def aclose(self) -> None:
            return None

    def _fake_build_runtime(**kwargs):
        build_calls.append(kwargs)
        return _Runtime()

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_composite_executor_runtime",
        _fake_build_runtime,
    )

    service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=None,
        auth_resolver=None,
        provider_store=None,
    )

    import asyncio

    asyncio.run(
        service.execute(
            _iteration_workflow("engine/ocr"),
            task_id="run-1",
            input_bindings={
                "input_1": TaskInputFile(
                    file_path="/tmp/input.txt",
                    filename="input.txt",
                    mime_type="text/plain",
                )
            },
            workspace_id="ws-1",
            node_executor=lambda *_args, **_kwargs: None,
        )
    )

    assert len(build_calls) == 1
