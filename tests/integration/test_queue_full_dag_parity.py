from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import sessionmaker

import app.worker_tasks as worker_tasks
from app.models.execution import NodeOutput
from app.providers.auth import AuthResolver, AuthResult, CredentialKind
from app.providers.auth_registry import registry
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import ModelProviderCreate, ProviderScope, ProviderType
from app.providers.store import ProviderStore
from app.services.dag_scheduler import DAGNode, NodeExecutionContext
from app.services.durable_workflow_execution import DurableWorkflowExecutionService
from app.services.engine_client import EngineClient, make_node_executor


def _database(tmp_path: Path) -> tuple[sessionmaker, Table, Table]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'queue_full_dag.sqlite'}")
    metadata = MetaData()
    task_runs = Table(
        "task_runs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("workspace_id", String),
        Column("duration_ms", Integer),
        Column("node_summary_json", Text),
        Column("result_preview", Text),
        Column("results_json", Text),
        Column("error", Text),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    node_runs = Table(
        "node_runs",
        metadata,
        Column("node_run_id", String, primary_key=True),
        Column("task_run_id", String),
        Column("node_id", String),
        Column("node_type", String),
        Column("status", String),
        Column("attempt", Integer),
        Column("duration_ms", Integer),
        Column("error", Text),
        Column("started_at", DateTime(timezone=False)),
        Column("completed_at", DateTime(timezone=False)),
        Column("updated_at", DateTime(timezone=False)),
    )
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False), task_runs, node_runs


def test_queue_worker_executes_every_engine_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, node_runs = _database(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: fernet)

    calls: list[str] = []

    async def _process(
        self: EngineClient,
        node_type: str,
        inputs: dict[str, NodeOutput],
        config: dict[str, object],
        headers: dict[str, str] | None = None,
        base_url: str | None = None,
        verify: bool = True,
    ) -> NodeOutput:
        _ = (self, inputs, config, headers, base_url, verify)
        calls.append(node_type)
        return NodeOutput(text=f"output-{len(calls)}")

    monkeypatch.setattr(EngineClient, "process", _process)

    source = tmp_path / "source.txt"
    source.write_text("queue input", encoding="utf-8")
    result = worker_tasks.execute_workflow_task_sync(
        "task_full_dag",
        {
            "nodes": [
                {"id": "input", "type": "input/text", "config": {}},
                {"id": "first", "type": "engine/text", "config": {}},
                {"id": "second", "type": "engine/text", "config": {}},
                {"id": "end", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "input", "target": "first"},
                {"source": "first", "target": "second"},
                {"source": "second", "target": "end"},
            ],
        },
        {
            "input": {
                "file_path": str(source),
                "filename": source.name,
                "mime_type": "text/plain",
                "workspace_id": "ws_queue",
            }
        },
        context_data={"workspace_id": "ws_queue"},
    )

    assert result["status"] == "completed"
    assert calls == ["engine/text", "engine/text"]
    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "task_full_dag")
            ).scalar_one()
            == "completed"
        )
        results_json = session.execute(
            select(task_runs.c.results_json).where(task_runs.c.id == "task_full_dag")
        ).scalar_one()
        assert '"content": "output-2"' in results_json
        assert set(
            session.execute(
                select(node_runs.c.node_id).where(node_runs.c.task_run_id == "task_full_dag")
            ).scalars()
        ) == {"input", "first", "second", "end"}


def test_serial_and_queue_resolve_same_workspace_provider_routing_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, _task_runs, _node_runs = _database(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    auth_type = "test_bearer_auth"
    plugin_module = ModuleType("test_queue_provider_plugin")
    plugin_registration_count = 0

    async def _resolve_test_bearer(*_args: object, **_kwargs: object) -> AuthResult:
        return AuthResult(kind=CredentialKind.bearer, credential="plugin-token")

    def _register_plugin() -> None:
        nonlocal plugin_registration_count
        plugin_registration_count += 1
        if not registry.has(auth_type):
            registry.register(auth_type, _resolve_test_bearer)

    plugin_module.register = _register_plugin  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, plugin_module.__name__, plugin_module)
    monkeypatch.setenv("PROVIDER_PLUGIN_MODULES", plugin_module.__name__)

    # Simulate the API process bootstrap. The queue path below must perform
    # its own bootstrap after this process-local strategy is removed.
    _register_plugin()
    provider_db = init_db(tmp_path / "providers.db")
    key = Fernet.generate_key().decode()
    fernet = get_fernet(key)
    store = ProviderStore(provider_db, fernet)
    provider = store.create_provider(
        ModelProviderCreate(
            name="Workspace Text",
            provider_type=ProviderType.engine_service,
            engine_category="text",
            base_url="https://text-provider.example",
            auth_type=auth_type,
            extra_config={
                "ssl_verify": False,
                "fixed_config": {"parser": "strict"},
            },
            scope=ProviderScope.workspace,
            workspace_id="ws_queue",
        )
    )
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: provider_db)
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: fernet)

    calls: list[dict[str, object]] = []

    async def _process(
        self: EngineClient,
        node_type: str,
        inputs: dict[str, NodeOutput],
        config: dict[str, object],
        headers: dict[str, str] | None = None,
        base_url: str | None = None,
        verify: bool = True,
        provider_request: bool = False,
    ) -> NodeOutput:
        _ = (self, inputs)
        calls.append(
            {
                "node_type": node_type,
                "config": config,
                "headers": headers,
                "base_url": base_url,
                "verify": verify,
                "provider_request": provider_request,
            }
        )
        return NodeOutput(text="provider-output")

    monkeypatch.setattr(EngineClient, "process", _process)
    serial_client = EngineClient()
    serial_executor = make_node_executor(
        serial_client,
        auth_resolver=AuthResolver(fernet=fernet),
        provider_resolver=lambda provider_id: store.get_for_runtime(provider_id, "ws_queue"),
    )
    asyncio.run(
        serial_executor(
            DAGNode(
                node_id="engine",
                node_type="engine/text",
                config={"provider_id": provider.id, "parser": "loose"},
                named_inputs={},
                dependencies=set(),
            ),
            {},
        )
    )
    asyncio.run(serial_client.close())
    serial_call = calls.pop()
    assert store.get_for_runtime(provider.id, "ws_other") is None
    registry.unregister(auth_type)

    source = tmp_path / "source.txt"
    source.write_text("queue input", encoding="utf-8")
    workflow_def: dict[str, object] = {
        "nodes": [
            {"id": "input", "type": "input/text", "config": {}},
            {
                "id": "engine",
                "type": "engine/text",
                "config": {"provider_id": provider.id, "parser": "loose"},
            },
            {"id": "end", "type": "end/final", "config": {}},
        ],
        "connections": [
            {"source": "input", "target": "engine"},
            {"source": "engine", "target": "end"},
        ],
    }
    input_data: dict[str, object] = {
        "input": {
            "file_path": str(source),
            "filename": source.name,
            "mime_type": "text/plain",
            "workspace_id": "ws_queue",
        }
    }

    for task_id in ("task_provider_contract", "task_provider_contract_repeat"):
        result = worker_tasks.execute_workflow_task_sync(
            task_id,
            workflow_def,
            input_data,
            context_data={"workspace_id": "ws_queue"},
        )
        assert result["status"] == "completed"

    provider_calls = [call for call in calls if call["node_type"] == "engine/text"]
    expected_call = {
        "node_type": "engine/text",
        "config": {"parser": "strict"},
        "headers": {"Authorization": "Bearer plugin-token"},
        "base_url": "https://text-provider.example",
        "verify": False,
        "provider_request": True,
    }
    assert serial_call == expected_call
    assert provider_calls == [serial_call, serial_call]
    assert plugin_registration_count == 2
    registry.unregister(auth_type)


def test_serial_and_queue_parity_for_adaptor_nodes_goes_through_shared_composite_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs = _database(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: fernet)

    composite_calls: list[tuple[str, tuple[str, ...], str | None]] = []

    def _fake_make_adaptor_node_executor(
        *,
        base_executor,
        definition_resolver,
        sandbox_client_factory,
        settings_getter=None,
    ):
        _ = (base_executor, definition_resolver, sandbox_client_factory, settings_getter)

        async def _executor(node, inputs, context=None):
            composite_calls.append(
                (
                    node.node_id,
                    tuple(sorted(inputs.keys())),
                    context.run_id if isinstance(context, NodeExecutionContext) else None,
                )
            )
            if node.node_type == "processor/adaptor":
                return NodeOutput(text=f"adaptor-{node.node_id}")
            return NodeOutput(text=f"base-{node.node_id}")

        return _executor

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.make_adaptor_node_executor",
        _fake_make_adaptor_node_executor,
    )

    scheduler = worker_tasks.DAGScheduler(
        event_store=worker_tasks._WorkerEventStore(),
        node_registry=worker_tasks.NodeRegistryService(),
        storage=worker_tasks.get_storage(),
    )
    serial_service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=EngineClient(),
        auth_resolver=AuthResolver(fernet=fernet),
        provider_store=ProviderStore(tmp_path / "providers.db", fernet),
    )
    source = tmp_path / "source.txt"
    source.write_text("queue input", encoding="utf-8")
    input_bindings = {
        "input": worker_tasks.TaskInputFile(
            file_path=str(source),
            filename=source.name,
            mime_type="text/plain",
            workspace_id="ws_queue",
        )
    }
    workflow = worker_tasks.WorkflowDefinition.model_validate(
        {
            "nodes": [
                {"id": "input", "type": "input/text", "config": {}},
                {
                    "id": "adaptor",
                    "type": "processor/adaptor",
                    "config": {"code": "def main(inputs):\n    return {'text': 'ok'}"},
                },
                {"id": "end", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "input", "target": "adaptor", "target_port": "input"},
                {"source": "adaptor", "target": "end", "target_port": "input"},
            ],
        }
    )

    asyncio.run(
        serial_service.execute(
            workflow,
            task_id="serial-adaptor",
            input_bindings=input_bindings,
            workspace_id="ws_queue",
        )
    )

    queue_result = worker_tasks.execute_workflow_task_sync(
        "queue-adaptor",
        {
            "nodes": [
                {"id": "input", "type": "input/text", "config": {}},
                {
                    "id": "adaptor",
                    "type": "processor/adaptor",
                    "config": {"code": "def main(inputs):\n    return {'text': 'ok'}"},
                },
                {"id": "end", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "input", "target": "adaptor", "target_port": "input"},
                {"source": "adaptor", "target": "end", "target_port": "input"},
            ],
        },
        {
            "input": {
                "file_path": str(source),
                "filename": source.name,
                "mime_type": "text/plain",
                "workspace_id": "ws_queue",
            }
        },
        context_data={"workspace_id": "ws_queue"},
    )

    assert queue_result["status"] == "completed"
    adaptor_calls = [call for call in composite_calls if call[0] == "adaptor"]
    assert adaptor_calls == [
        ("adaptor", ("input",), "serial-adaptor"),
        ("adaptor", ("input",), "queue-adaptor"),
    ]
    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "queue-adaptor")
            ).scalar_one()
            == "completed"
        )


def test_serial_and_queue_parity_for_iteration_nodes_uses_shared_composite_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, task_runs, _node_runs = _database(tmp_path)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_tasks, "get_db_path", lambda: tmp_path / "providers.db")
    fernet = get_fernet(Fernet.generate_key().decode())
    monkeypatch.setattr(worker_tasks, "get_fernet", lambda: fernet)

    build_calls: list[str] = []

    class _Runtime:
        async def executor(self, node, inputs, context=None):
            _ = (inputs, context)
            if node.node_type == "processor/iteration":
                return NodeOutput(
                    structured={
                        "kind": "iteration_result",
                        "items": [],
                        "total": 0,
                        "success_count": 0,
                        "error_count": 0,
                    }
                )
            return NodeOutput(text=f"base-{node.node_id}")

        async def aclose(self) -> None:
            return None

    def _fake_build_runtime(**kwargs):
        _ = kwargs
        build_calls.append("called")
        return _Runtime()

    monkeypatch.setattr(
        "app.services.durable_workflow_execution.build_composite_executor_runtime",
        _fake_build_runtime,
    )

    workflow = worker_tasks.WorkflowDefinition.model_validate(
        {
            "nodes": [
                {"id": "input", "type": "input/text", "config": {}},
                {
                    "id": "iter",
                    "type": "processor/iteration",
                    "config": {
                        "engine_node_type": "engine/ocr",
                        "engine_config": {},
                        "iterate_over": "binary",
                        "item_input_port": "image",
                        "mode": "sequential",
                        "max_concurrency": 5,
                        "error_handling": "terminate",
                    },
                },
                {"id": "end", "type": "end/final", "config": {}},
            ],
            "connections": [
                {"source": "input", "target": "iter", "target_port": "input"},
                {"source": "iter", "target": "end", "target_port": "input"},
            ],
        }
    )
    source = tmp_path / "source.txt"
    source.write_text("queue input", encoding="utf-8")
    input_bindings = {
        "input": worker_tasks.TaskInputFile(
            file_path=str(source),
            filename=source.name,
            mime_type="text/plain",
            workspace_id="ws_queue",
        )
    }

    scheduler = worker_tasks.DAGScheduler(
        event_store=worker_tasks._WorkerEventStore(),
        node_registry=worker_tasks.NodeRegistryService(),
        storage=worker_tasks.get_storage(),
    )
    serial_service = DurableWorkflowExecutionService(
        dag_scheduler=scheduler,
        engine_client=EngineClient(),
        auth_resolver=AuthResolver(fernet=fernet),
        provider_store=ProviderStore(tmp_path / "providers.db", fernet),
    )

    asyncio.run(
        serial_service.execute(
            workflow,
            task_id="serial-iteration",
            input_bindings=input_bindings,
            workspace_id="ws_queue",
            node_executor=lambda *_args, **_kwargs: NodeOutput(text="base"),
        )
    )

    queue_result = worker_tasks.execute_workflow_task_sync(
        "queue-iteration",
        workflow.model_dump(mode="json"),
        {
            "input": {
                "file_path": str(source),
                "filename": source.name,
                "mime_type": "text/plain",
                "workspace_id": "ws_queue",
            }
        },
        context_data={"workspace_id": "ws_queue"},
    )

    assert queue_result["status"] == "completed"
    assert build_calls == ["called", "called"]
    with session_factory() as session:
        assert (
            session.execute(
                select(task_runs.c.status).where(task_runs.c.id == "queue-iteration")
            ).scalar_one()
            == "completed"
        )
