from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.agent_sessions as session_module
import app.services.agent_tool_gateway as gateway_module
from app.api.chatbox import _record_runtime_checkpoint, _validated_checkpoint_path
from app.config import Settings, get_settings
from app.db.base import Base
from app.errors import AppError
from app.models.db.agent_session_credential import AgentSessionCredential
from app.models.db.chatbox_session import ChatboxSession
from app.models.db.tool_approval_request import ToolApprovalRequest
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.db.workspace_member import WorkspaceMember
from app.services.agent_session_credentials import (
    AgentSessionCredentialService,
    utcnow_naive,
)
from app.services.agent_sessions import AgentSessionService
from app.services.agent_tool_gateway import (
    AgentToolGateway,
    AgentToolGatewayError,
    AgentToolGatewayGrant,
    decide_approval,
    require_agent_tool_gateway_grant,
)
from app.services.pi_runtime import PiRuntimeError

REGISTERED_AGENT_OPERATIONS = {
    "workflow.validate",
    "workflow.list",
    "workflow.get",
    "workflow.create",
    "workflow.update",
    "workflow.version.list",
    "workflow.version.get",
    "workflow.execute",
    "workflow.publish",
    "workflow.delete",
    "workflow.version.restore",
    "workflow.draft-run",
    "workflow.node-run",
    "run.list",
    "run.get",
    "run.wait",
    "run.results",
    "run.cancel",
    "run.retry",
    "run.node.get",
    "file.list",
    "file.get",
    "test-set.list",
    "test-set.get",
    "test-set.document.list",
    "test-set.document.get",
    "ground-truth.get",
    "ground-truth.version.list",
    "ground-truth.version.get",
    "evaluation.list",
    "evaluation.get",
    "evaluation.wait",
    "evaluation.results",
    "evaluation.result",
    "evaluation.create",
    "evaluation.cancel",
    "evaluation.comparison.get",
    "provider.list",
    "provider.get",
    "provider.model.list",
    "node-type.list",
}

EXCLUDED_AGENT_OPERATIONS = {
    "file.upload",
    "file.download",
    "file.delete",
    "workflow.export",
    "workflow.import",
    "run.download",
    "run.node.image",
    "test-set.document.download",
    "test-set.document.thumbnail",
    "test-set.document.upload",
    "test-set.document.delete",
    "ground-truth.upload",
    "evaluation.comparison.refresh",
    "provider.test",
    "provider.health",
    "provider.model.test",
    "engine.health",
    "test-set.create",
    "test-set.update",
    "test-set.delete",
    "engine.list",
    "engine.get",
    "run.reset",
    "run.node.retry",
    "run.node.rerun",
}


def test_empty_agent_session_can_defer_checkpoint_file_creation(tmp_path: Path) -> None:
    handle = SimpleNamespace(checkpoint_path=tmp_path / "not-created-yet.jsonl")

    _record_runtime_checkpoint("session-a", handle, allow_missing=True)

    with pytest.raises(PiRuntimeError, match="checkpoint is unavailable"):
        _record_runtime_checkpoint("session-a", handle)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table_name in (
        "users",
        "workspaces",
        "workspace_members",
        "chatbox_sessions",
        "chatbox_session_selections",
        "agent_session_credentials",
        "tool_approval_requests",
    ):
        Base.metadata.tables[table_name].create(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(factory: sessionmaker[Session]) -> None:
    with factory() as database:
        database.add_all(
            [
                UserAccount(
                    id="user-a",
                    email="agent@example.test",
                    password_hash="unused",
                    name="Agent",
                    last_workspace_id="workspace-a",
                ),
                Workspace(
                    id="workspace-a",
                    name="Workspace A",
                    slug=None,
                    description=None,
                    owner_user_id="user-a",
                ),
                WorkspaceMember(
                    id="member-a",
                    workspace_id="workspace-a",
                    user_id="user-a",
                    role="owner",
                ),
                ChatboxSession(
                    id="session-a",
                    workspace_id="workspace-a",
                    user_id="user-a",
                    provider_id="provider-a",
                    session_state="active",
                    runtime_state="idle",
                    runtime_generation=1,
                ),
            ]
        )
        database.commit()


def test_agent_session_credentials_rotate_and_enforce_live_scope() -> None:
    factory = _session_factory()
    _seed(factory)
    settings = Settings(
        auth_session_secret="agent-session-test-secret",
        workspace_rbac_enforced=True,
    )
    service = AgentSessionCredentialService(session_factory=factory, settings=settings)

    first = service.issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )
    assert first.raw_token.startswith("pra_")
    assert first.raw_token not in first.record.token_hash
    context = service.require_authenticated(
        first.raw_token,
        requested_session_id="session-a",
        requested_workspace_id="workspace-a",
    )
    assert context.auth_kind == "agent_session_token"
    assert context.workspace_id == "workspace-a"

    with pytest.raises(AppError):
        service.require_authenticated(
            first.raw_token,
            requested_session_id="another-session",
            requested_workspace_id="workspace-a",
        )

    second = service.issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )
    with pytest.raises(AppError):
        service.require_authenticated(
            first.raw_token,
            requested_session_id="session-a",
            requested_workspace_id="workspace-a",
        )

    with factory() as database:
        session = database.get(ChatboxSession, "session-a")
        assert session is not None
        session.session_state = "paused"
        database.commit()
    with pytest.raises(AppError):
        service.require_authenticated(
            second.raw_token,
            requested_session_id="session-a",
            requested_workspace_id="workspace-a",
        )

    with factory() as database:
        session = database.get(ChatboxSession, "session-a")
        assert session is not None
        session.session_state = "active"
        session.runtime_generation = 2
        database.commit()
    third = service.issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=2,
    )
    with factory() as database:
        membership = database.scalar(select(WorkspaceMember))
        assert membership is not None
        database.delete(membership)
        database.commit()
    with pytest.raises(AppError):
        service.require_authenticated(
            third.raw_token,
            requested_session_id="session-a",
            requested_workspace_id="workspace-a",
        )


def test_managed_grant_argv_and_approval_are_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    _seed(factory)
    monkeypatch.setattr(gateway_module, "SessionLocal", factory)
    settings = Settings(
        auth_session_secret="agent-session-test-secret",
        workspace_rbac_enforced=True,
    )
    credential = AgentSessionCredentialService(
        session_factory=factory,
        settings=settings,
    ).issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )
    grant = AgentToolGatewayGrant(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
        catalog_version="0.1",
        credential=credential,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(agent_tool_gateway_grants={"internal-grant": grant})
    )
    assert require_agent_tool_gateway_grant(app, "internal-grant") is grant

    assert AgentToolGateway._argv(
        "workflow.list",
        {"page": 2, "limit": 10, "sort": "name:asc", "query": "invoice"},
    ) == [
        "workflow",
        "list",
        "--page",
        "2",
        "--limit",
        "10",
        "--sort",
        "name:asc",
        "--query",
        "invoice",
    ]
    with pytest.raises(AgentToolGatewayError, match="arguments are invalid"):
        AgentToolGateway._argv("workflow.list", {"host": "https://attacker.invalid"})

    approval = ToolApprovalRequest(
        id="approval-a",
        user_id="user-a",
        workspace_id="workspace-a",
        agent_session_id="session-a",
        runtime_generation=1,
        tool_call_id="tool-call-a",
        operation="workflow.execute",
        argument_digest="digest-a",
        argument_summary='{"workflow_id":"workflow-a"}',
        status="pending",
        created_at=utcnow_naive(),
        expires_at=utcnow_naive() + timedelta(minutes=1),
    )
    with factory() as database:
        database.add(approval)
        database.commit()
    decided = decide_approval(
        approval_id="approval-a",
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        approved=False,
    )
    assert decided.status == "rejected"
    with pytest.raises(RuntimeError, match="no longer pending"):
        decide_approval(
            approval_id="approval-a",
            agent_session_id="session-a",
            user_id="user-a",
            workspace_id="workspace-a",
            approved=True,
        )

    with factory() as database:
        membership = database.scalar(select(WorkspaceMember))
        assert membership is not None
        database.delete(membership)
        database.commit()
    with pytest.raises(AgentToolGatewayError, match="membership"):
        require_agent_tool_gateway_grant(app, "internal-grant")


@pytest.mark.asyncio
async def test_managed_output_reader_stops_at_the_limit() -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(b"12345")
    stream.feed_eof()
    with pytest.raises(AgentToolGatewayError, match="exceeded"):
        await gateway_module._read_bounded(stream, limit=4, code="TOOL_OUTPUT_LIMIT")


@pytest.mark.asyncio
async def test_managed_executor_uses_fixed_argv_and_private_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    _seed(factory)
    credential = AgentSessionCredentialService(
        session_factory=factory,
        settings=Settings(auth_session_secret="agent-session-test-secret"),
    ).issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )
    grant = AgentToolGatewayGrant(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
        catalog_version="0.1",
        credential=credential,
    )
    storage_root = tmp_path / "storage"
    (storage_root / "workspaces" / "workspace-a").mkdir(parents=True)
    executor = object.__new__(AgentToolGateway)
    executor.settings = SimpleNamespace(
        temp_dir=str(tmp_path),
        storage_root=str(storage_root),
        chatbox_internal_proxy_base_url="http://127.0.0.1:8000",
        agent_tool_timeout_seconds=5,
        agent_tool_output_max_bytes=4096,
    )
    captured: dict[str, object] = {}

    class FakeStdin:
        def __init__(self) -> None:
            self.payload = bytearray()

        def write(self, payload: bytes) -> None:
            self.payload.extend(payload)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            captured["stdin"] = bytes(self.payload)

        async def wait_closed(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_data(
                json.dumps(
                    {
                        "schema_version": "pressroom-envelope.v1",
                        "ok": True,
                        "data": {"items": []},
                        "error": None,
                        "request_id": "request-a",
                    }
                ).encode()
            )
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_subprocess(*command: str, **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        env = kwargs["env"]
        assert isinstance(env, dict)
        captured["token"] = Path(env["PRESSROOM_TOKEN_FILE"]).read_text(encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    definition = {"nodes": [], "connections": []}
    argv = AgentToolGateway._argv(
        "workflow.create",
        {"name": "OCR", "definition": definition},
    )
    stdin_payload = AgentToolGateway._stdin_payload(
        "workflow.create",
        {"name": "OCR", "definition": definition},
    )
    envelope = await executor._run_cli(
        grant=grant,
        argv=argv,
        stdin_payload=stdin_payload,
    )

    command = captured["command"]
    assert isinstance(command, tuple)
    assert command[1:4] == ("-m", "pressroom_cli", "workflow")
    assert "--definition" in command
    assert "-" in command
    assert "--yes" not in command
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "shell" not in kwargs
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["PRESSROOM_WORKSPACE_ID"] == "workspace-a"
    assert env["PRESSROOM_AGENT_SESSION_ID"] == "session-a"
    assert captured["token"] == credential.raw_token
    assert json.loads(captured["stdin"]) == definition
    assert envelope["ok"] is True


def test_gateway_catalog_separates_approval_from_cli_confirmation_flag() -> None:
    catalog = AgentToolGateway._load_catalog()

    assert len(catalog) == 41
    assert set(catalog) == REGISTERED_AGENT_OPERATIONS
    assert not set(catalog) & EXCLUDED_AGENT_OPERATIONS
    assert all(
        command.get("requires_platform_approval") is True
        for command in catalog.values()
        if command["exposure"] == "agent-confirmation"
    )
    assert catalog["workflow.create"]["requires_platform_approval"] is True
    assert catalog["workflow.create"]["cli_requires_yes_flag"] is False
    assert catalog["workflow.execute"]["requires_platform_approval"] is True
    assert catalog["workflow.execute"]["cli_requires_yes_flag"] is True


@pytest.mark.parametrize(
    ("operation", "args", "expected"),
    [
        ("workflow.publish", {"workflow_id": "wf-1"}, ["workflow", "publish", "wf-1"]),
        ("workflow.delete", {"workflow_id": "wf-1"}, ["workflow", "delete", "wf-1"]),
        (
            "workflow.version.restore",
            {"workflow_id": "wf-1", "version": 3},
            ["workflow", "version", "restore", "wf-1", "3"],
        ),
        (
            "workflow.draft-run",
            {"definition": {"nodes": []}, "file_ids": ["file-1"], "run_name": "OCR"},
            [
                "workflow",
                "draft-run",
                "--definition",
                "-",
                "--file-id",
                "file-1",
                "--run-name",
                "OCR",
            ],
        ),
        (
            "workflow.node-run",
            {"definition": {"nodes": []}, "node_id": "ocr", "file_ids": ["file-1"]},
            [
                "workflow",
                "node-run",
                "--definition",
                "-",
                "--node-id",
                "ocr",
                "--file-id",
                "file-1",
            ],
        ),
        (
            "run.list",
            {"page": 2, "limit": 10, "status": "completed", "workflow_id": "wf-1"},
            [
                "run",
                "list",
                "--page",
                "2",
                "--limit",
                "10",
                "--status",
                "completed",
                "--workflow-id",
                "wf-1",
            ],
        ),
        ("run.get", {"run_id": "run-1"}, ["run", "get", "run-1"]),
        (
            "run.wait",
            {"run_id": "run-1", "wait_timeout": 30, "interval": 0.5},
            ["run", "wait", "run-1", "--wait-timeout", "30", "--interval", "0.5"],
        ),
        ("run.results", {"run_id": "run-1"}, ["run", "results", "run-1"]),
        ("run.cancel", {"run_id": "run-1"}, ["run", "cancel", "run-1"]),
        ("run.retry", {"run_id": "run-1"}, ["run", "retry", "run-1"]),
        (
            "run.node.get",
            {"run_id": "run-1", "node_id": "ocr"},
            ["run", "node", "get", "run-1", "ocr"],
        ),
        (
            "file.list",
            {"page": 2, "limit": 25, "query": "invoice"},
            ["file", "list", "--page", "2", "--limit", "25", "--query", "invoice"],
        ),
        ("file.get", {"file_id": "file-1"}, ["file", "get", "file-1"]),
        ("test-set.list", {}, ["test-set", "list"]),
        ("test-set.get", {"test_set_id": "set-1"}, ["test-set", "get", "set-1"]),
        (
            "test-set.document.list",
            {"test_set_id": "set-1"},
            ["test-set", "document", "list", "set-1"],
        ),
        (
            "test-set.document.get",
            {"test_set_id": "set-1", "document_id": "doc-1"},
            ["test-set", "document", "get", "set-1", "doc-1"],
        ),
        (
            "ground-truth.get",
            {"test_set_id": "set-1", "document_id": "doc-1"},
            ["ground-truth", "get", "set-1", "doc-1"],
        ),
        (
            "ground-truth.version.list",
            {"test_set_id": "set-1", "document_id": "doc-1"},
            ["ground-truth", "version", "list", "set-1", "doc-1"],
        ),
        (
            "ground-truth.version.get",
            {"test_set_id": "set-1", "document_id": "doc-1", "version": 2},
            ["ground-truth", "version", "get", "set-1", "doc-1", "2"],
        ),
        ("evaluation.list", {"test_set_id": "set-1"}, ["evaluation", "list", "set-1"]),
        (
            "evaluation.get",
            {"evaluation_id": "eval-1"},
            ["evaluation", "get", "eval-1"],
        ),
        (
            "evaluation.wait",
            {"evaluation_id": "eval-1", "wait_timeout": 45, "interval": 1.5},
            [
                "evaluation",
                "wait",
                "eval-1",
                "--wait-timeout",
                "45",
                "--interval",
                "1.5",
            ],
        ),
        (
            "evaluation.results",
            {"evaluation_id": "eval-1"},
            ["evaluation", "results", "eval-1"],
        ),
        (
            "evaluation.result",
            {"evaluation_id": "eval-1", "result_id": "result-1"},
            ["evaluation", "result", "eval-1", "result-1"],
        ),
        (
            "evaluation.create",
            {
                "test_set_id": "set-1",
                "workflow_id": "wf-1",
                "name": "Baseline",
                "document_ids": ["doc-1"],
                "client_request_id": "request-1",
            },
            [
                "evaluation",
                "create",
                "set-1",
                "--workflow-id",
                "wf-1",
                "--name",
                "Baseline",
                "--document-id",
                "doc-1",
                "--client-request-id",
                "request-1",
            ],
        ),
        (
            "evaluation.cancel",
            {"evaluation_id": "eval-1"},
            ["evaluation", "cancel", "eval-1"],
        ),
        (
            "evaluation.comparison.get",
            {"evaluation_id": "eval-1", "result_id": "result-1"},
            ["evaluation", "comparison", "get", "eval-1", "result-1"],
        ),
        (
            "provider.list",
            {"category": "ocr", "provider_type": "engine_service", "all": True},
            [
                "provider",
                "list",
                "--category",
                "ocr",
                "--provider-type",
                "engine_service",
                "--all",
            ],
        ),
        ("provider.get", {"provider_id": "provider-1"}, ["provider", "get", "provider-1"]),
        (
            "provider.model.list",
            {"category": "vlm"},
            ["provider", "model", "list", "--category", "vlm"],
        ),
        ("node-type.list", {}, ["node-type", "list"]),
    ],
)
def test_gateway_maps_each_new_agent_operation_to_fixed_argv(
    operation: str, args: dict[str, object], expected: list[str]
) -> None:
    assert AgentToolGateway._argv(operation, args) == expected


def test_gateway_validates_new_operation_arguments_and_structured_input() -> None:
    definition = {"nodes": [], "connections": []}
    assert (
        json.loads(
            AgentToolGateway._stdin_payload("workflow.draft-run", {"definition": definition})
            or b"null"
        )
        == definition
    )
    assert (
        json.loads(
            AgentToolGateway._stdin_payload("workflow.node-run", {"definition": definition})
            or b"null"
        )
        == definition
    )

    with pytest.raises(AgentToolGatewayError, match="arguments are invalid"):
        AgentToolGateway._argv("file.list", {"host": "https://attacker.invalid"})
    with pytest.raises(AgentToolGatewayError, match="file_ids is invalid"):
        AgentToolGateway._argv(
            "workflow.draft-run", {"definition": definition, "file_ids": "file-1"}
        )
    with pytest.raises(AgentToolGatewayError, match="wait_timeout is invalid"):
        AgentToolGateway._argv("run.wait", {"run_id": "run-1", "wait_timeout": True})
    with pytest.raises(AgentToolGatewayError, match="all must be a boolean"):
        AgentToolGateway._argv("provider.list", {"all": "true"})
    with pytest.raises(AgentToolGatewayError, match="not registered"):
        AgentToolGateway._argv("file.upload", {"file": "C:/secret.png"})

    gateway = object.__new__(AgentToolGateway)
    gateway.settings = SimpleNamespace(agent_tool_timeout_seconds=45)
    assert gateway._runtime_bounded_args("run.wait", {"run_id": "run-1"}) == {
        "run_id": "run-1",
        "wait_timeout": 30.0,
    }
    with pytest.raises(AgentToolGatewayError, match="wait_timeout is invalid"):
        gateway._runtime_bounded_args(
            "evaluation.wait", {"evaluation_id": "eval-1", "wait_timeout": 43}
        )


@pytest.mark.asyncio
async def test_cancelling_confirmation_cancels_the_bound_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    _seed(factory)
    monkeypatch.setattr(gateway_module, "SessionLocal", factory)
    credential = AgentSessionCredentialService(
        session_factory=factory,
        settings=Settings(auth_session_secret="agent-session-test-secret"),
    ).issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )
    grant = AgentToolGatewayGrant(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
        catalog_version="0.1",
        credential=credential,
    )
    executor = object.__new__(AgentToolGateway)
    executor.catalog = {
        "workflow.execute": {
            "requires_platform_approval": True,
            "cli_requires_yes_flag": True,
        },
    }
    executor.settings = SimpleNamespace(agent_tool_approval_ttl_seconds=60)
    task = asyncio.create_task(
        executor.execute(
            grant=grant,
            catalog_version="0.1",
            operation="workflow.execute",
            args={"workflow_id": "workflow-a"},
            tool_call_id="tool-call-a",
        )
    )
    approval_id: str | None = None
    for _ in range(20):
        with factory() as database:
            approval = database.scalar(select(ToolApprovalRequest))
            approval_id = approval.id if approval is not None else None
        if approval_id is not None:
            break
        await asyncio.sleep(0.01)
    assert approval_id is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with factory() as database:
        approval = database.get(ToolApprovalRequest, approval_id)
        assert approval is not None
        assert approval.status == "cancelled"


def test_revoke_user_marks_all_active_credentials_revoked() -> None:
    factory = _session_factory()
    _seed(factory)
    service = AgentSessionCredentialService(
        session_factory=factory,
        settings=Settings(auth_session_secret="agent-session-test-secret"),
    )
    issued = service.issue(
        agent_session_id="session-a",
        user_id="user-a",
        workspace_id="workspace-a",
        runtime_generation=1,
    )

    service.revoke_user("user-a")

    with factory() as database:
        record = database.get(AgentSessionCredential, issued.record.id)
        assert record is not None
        assert record.credential_state == "revoked"
        assert record.revoked_at is not None


def test_agent_sessions_switch_without_sharing_generation_or_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    _seed(factory)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    service = AgentSessionService()
    first = service.create_draft(
        user_id="user-a",
        workspace_id="workspace-a",
        provider_id="provider-a",
    )
    first_active = service.activate(
        session_id=first.id,
        user_id="user-a",
        workspace_id="workspace-a",
    ).session
    second = service.create_draft(
        user_id="user-a",
        workspace_id="workspace-a",
        provider_id="provider-a",
    )
    second_active = service.activate(
        session_id=second.id,
        user_id="user-a",
        workspace_id="workspace-a",
    ).session

    assert first_active.runtime_generation == 1
    assert second_active.runtime_generation == 1
    current = service.current(user_id="user-a", workspace_id="workspace-a")
    assert current is not None
    assert current.id == second.id
    with factory() as database:
        persisted_first = database.get(ChatboxSession, first.id)
        assert persisted_first is not None
        assert persisted_first.session_state == "paused"

    suspended = service.suspend(
        session_id=second.id,
        user_id="user-a",
        workspace_id="workspace-a",
    )
    assert suspended.session_state == "paused"
    current = service.current(user_id="user-a", workspace_id="workspace-a")
    assert current is not None
    assert current.id == second.id
    reactivated = service.activate(
        session_id=second.id,
        user_id="user-a",
        workspace_id="workspace-a",
    ).session
    assert reactivated.runtime_generation == 2

    resumed = service.activate(
        session_id=first.id,
        user_id="user-a",
        workspace_id="workspace-a",
    ).session
    assert resumed.runtime_generation == 2
    archived = service.archive(
        session_id=second.id,
        user_id="user-a",
        workspace_id="workspace-a",
    )
    assert archived.session_state == "archived"
    listed_ids = [
        item.id
        for item in service.list_for_user_workspace(user_id="user-a", workspace_id="workspace-a")
    ]
    assert first.id in listed_ids
    assert second.id not in listed_ids


def test_agent_sessions_backfill_legacy_admission_navigation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    _seed(factory)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    service = AgentSessionService()
    draft = service.create_draft(
        user_id="user-a",
        workspace_id="workspace-a",
        provider_id="provider-a",
    )
    with factory() as database:
        persisted = database.get(ChatboxSession, draft.id)
        assert persisted is not None
        original_activity = persisted.last_activity_at
        persisted.messages_json = [
            {
                "id": "admission-user-legacy",
                "role": "user",
                "content": [{"type": "text", "text": "Write a poem about sunsets."}],
            },
            {
                "id": "admission-platform-legacy",
                "role": "platform",
                "content": [
                    {
                        "type": "admission",
                        "status": "reject_out_of_scope",
                        "reasonCode": "not_pressroom_scope",
                    }
                ],
            },
        ]
        database.commit()

    listed = service.list_for_user_workspace(user_id="user-a", workspace_id="workspace-a")

    legacy = next(session for session in listed if session.id == draft.id)
    assert legacy.title == "Write a poem about sunsets."
    assert legacy.preview == "Write a poem about sunsets."
    assert legacy.first_settled_at is None
    assert legacy.last_activity_at == original_activity
    with factory() as database:
        persisted = database.get(ChatboxSession, draft.id)
        assert persisted is not None
        assert persisted.title == "Write a poem about sunsets."
        assert persisted.preview == "Write a poem about sunsets."


def test_checkpoint_integrity_and_private_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
    get_settings.cache_clear()
    session = ChatboxSession(
        id="session-a",
        workspace_id="workspace-a",
        user_id="user-a",
        provider_id="provider-a",
    )
    checkpoint_dir = storage_root / ".agent-sessions" / "workspace-a" / "session-a"
    checkpoint_dir.mkdir(parents=True)
    checkpoint = checkpoint_dir / "session.jsonl"
    checkpoint.write_bytes(b'{"type":"session"}\n')
    session.checkpoint_ref = str(checkpoint)
    session.checkpoint_schema_version = 3
    session.checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    assert _validated_checkpoint_path(session) == checkpoint.resolve()
    checkpoint.write_bytes(b"corrupt")
    with pytest.raises(PiRuntimeError, match="integrity"):
        _validated_checkpoint_path(session)

    outside = storage_root / "outside.jsonl"
    outside.write_bytes(b"outside")
    session.checkpoint_ref = str(outside)
    session.checkpoint_hash = None
    with pytest.raises(PiRuntimeError, match="unavailable"):
        _validated_checkpoint_path(session)
    get_settings.cache_clear()


def test_legacy_checkpoint_moves_into_isolated_runtime_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    checkpoint_root = tmp_path / "runtime-checkpoints"
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("AGENT_CHECKPOINT_ROOT", str(checkpoint_root))
    get_settings.cache_clear()
    session = ChatboxSession(
        id="session-a",
        workspace_id="workspace-a",
        user_id="user-a",
        provider_id="provider-a",
    )
    legacy_dir = storage_root / ".agent-sessions" / "workspace-a" / "session-a"
    legacy_dir.mkdir(parents=True)
    legacy_checkpoint = legacy_dir / "session.jsonl"
    legacy_checkpoint.write_bytes(b'{"type":"session"}\n')
    session.checkpoint_ref = str(legacy_checkpoint)
    session.checkpoint_schema_version = 3
    session.checkpoint_hash = hashlib.sha256(legacy_checkpoint.read_bytes()).hexdigest()

    migrated = _validated_checkpoint_path(session)

    assert migrated == (checkpoint_root / "workspace-a" / "session-a" / "session.jsonl").resolve()
    assert migrated.read_bytes() == legacy_checkpoint.read_bytes()
    assert legacy_checkpoint.is_file()

    migrated.write_bytes(b"conflict")
    with pytest.raises(PiRuntimeError, match="migration conflict"):
        _validated_checkpoint_path(session)
    get_settings.cache_clear()
