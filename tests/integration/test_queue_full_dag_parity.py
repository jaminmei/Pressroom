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
from app.services.dag_scheduler import DAGNode
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
