"""Agent Tool Gateway used by the built-in PressRoom Pi Extension."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sys
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update

from app.config import get_settings
from app.db.session import SessionLocal
from app.models.db.agent_session_credential import AgentSessionCredential
from app.models.db.chatbox_session import ChatboxSession
from app.models.db.tool_approval_request import ToolApprovalRequest
from app.models.db.workspace_member import WorkspaceMember
from app.services.agent_session_credentials import (
    AgentSessionCredentialService,
    IssuedAgentSessionCredential,
    utcnow_naive,
)

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parents[2] / "cli" / "catalog" / "tool-catalog.yaml"
PI_TOOL_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "cli" / "catalog" / "agent-tool-catalog.generated.json"
)
CLI_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "cli"
TOOL_CATALOG_VERSION = "0.1"
_TOOL_GRANT_HEADER = "X-DocConv-Tool-Grant"
_ROTATE_BEFORE_SECONDS = 120
_APPROVAL_POLL_SECONDS = 0.2
_MAX_STRUCTURED_INPUT_BYTES = 1_048_576


@dataclass(slots=True)
class AgentToolGatewayGrant:
    agent_session_id: str
    user_id: str
    workspace_id: str
    runtime_generation: int
    catalog_version: str
    credential: IssuedAgentSessionCredential


class AgentToolGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Transitional aliases keep the current implementation diff reviewable while
# all application-facing imports use Agent Tool Gateway terminology.
ManagedToolGrant = AgentToolGatewayGrant
ManagedToolExecutorError = AgentToolGatewayError


def _grants(app: Any) -> dict[str, ManagedToolGrant]:
    grants: dict[str, ManagedToolGrant] | None = getattr(
        app.state, "agent_tool_gateway_grants", None
    )
    if grants is None:
        grants = {}
        app.state.agent_tool_gateway_grants = grants
    return grants


def issue_managed_tool_grant(
    app: Any,
    *,
    agent_session_id: str,
    user_id: str,
    workspace_id: str,
    runtime_generation: int,
) -> str:
    revoke_managed_tool_grants(app, agent_session_id=agent_session_id)
    credential = AgentSessionCredentialService().issue(
        agent_session_id=agent_session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        runtime_generation=runtime_generation,
    )
    token = secrets.token_urlsafe(32)
    _grants(app)[token] = ManagedToolGrant(
        agent_session_id=agent_session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        runtime_generation=runtime_generation,
        catalog_version=TOOL_CATALOG_VERSION,
        credential=credential,
    )
    return token


def revoke_managed_tool_grants(app: Any, *, agent_session_id: str) -> None:
    grants = _grants(app)
    for token in [
        token for token, grant in grants.items() if grant.agent_session_id == agent_session_id
    ]:
        grants.pop(token, None)
    AgentSessionCredentialService().revoke_session(agent_session_id)
    cancel_pending_approvals(agent_session_id)


def revoke_managed_tool_grants_for_user(app: Any, *, user_id: str) -> None:
    session_ids = {
        grant.agent_session_id for grant in _grants(app).values() if grant.user_id == user_id
    }
    for session_id in session_ids:
        revoke_managed_tool_grants(app, agent_session_id=session_id)
    AgentSessionCredentialService().revoke_user(user_id)


def require_managed_tool_grant(app: Any, token: str | None) -> ManagedToolGrant:
    grant = _grants(app).get(token or "")
    if grant is None:
        raise ManagedToolExecutorError("TOOL_GRANT_INVALID", "Managed tool grant is invalid")
    with SessionLocal() as database:
        session = database.get(ChatboxSession, grant.agent_session_id)
        if (
            session is None
            or session.user_id != grant.user_id
            or session.workspace_id != grant.workspace_id
            or session.runtime_generation != grant.runtime_generation
            or session.session_state != "active"
        ):
            raise ManagedToolExecutorError("TOOL_GRANT_STALE", "Managed tool grant is stale")
        membership = database.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.user_id == grant.user_id,
                WorkspaceMember.workspace_id == grant.workspace_id,
            )
        )
        if membership is None:
            raise ManagedToolExecutorError(
                "TOOL_GRANT_STALE", "Workspace membership is unavailable"
            )
        credential = database.get(
            AgentSessionCredential,
            grant.credential.record.id,
        )
        if credential is None or credential.credential_state == "revoked":
            raise ManagedToolExecutorError(
                "TOOL_GRANT_STALE", "Agent Session credential was revoked"
            )
    return grant


def cancel_pending_approvals(agent_session_id: str) -> None:
    now = utcnow_naive()
    with SessionLocal() as database:
        database.execute(
            update(ToolApprovalRequest)
            .where(
                ToolApprovalRequest.agent_session_id == agent_session_id,
                ToolApprovalRequest.status.in_(("pending", "approved")),
            )
            .values(status="cancelled", decided_at=now)
        )
        database.commit()


def list_pending_approvals(
    *, agent_session_id: str, user_id: str, workspace_id: str
) -> list[ToolApprovalRequest]:
    now = utcnow_naive()
    with SessionLocal() as database:
        database.execute(
            update(ToolApprovalRequest)
            .where(
                ToolApprovalRequest.agent_session_id == agent_session_id,
                ToolApprovalRequest.status == "pending",
                ToolApprovalRequest.expires_at <= now,
            )
            .values(status="expired", decided_at=now)
        )
        database.commit()
        return list(
            database.scalars(
                select(ToolApprovalRequest)
                .where(
                    ToolApprovalRequest.agent_session_id == agent_session_id,
                    ToolApprovalRequest.user_id == user_id,
                    ToolApprovalRequest.workspace_id == workspace_id,
                    ToolApprovalRequest.status == "pending",
                )
                .order_by(ToolApprovalRequest.created_at.asc())
            )
        )


def decide_approval(
    *,
    approval_id: str,
    agent_session_id: str,
    user_id: str,
    workspace_id: str,
    approved: bool,
) -> ToolApprovalRequest:
    now = utcnow_naive()
    with SessionLocal() as database:
        approval = database.get(ToolApprovalRequest, approval_id)
        if (
            approval is None
            or approval.agent_session_id != agent_session_id
            or approval.user_id != user_id
            or approval.workspace_id != workspace_id
        ):
            raise LookupError("Tool approval not found")
        assert isinstance(approval, ToolApprovalRequest)
        if approval.status != "pending" or approval.expires_at <= now:
            if approval.status == "pending":
                approval.status = "expired"
                approval.decided_at = now
                database.commit()
            raise RuntimeError("Tool approval is no longer pending")
        approval.status = "approved" if approved else "rejected"
        approval.decided_at = now
        database.commit()
        database.refresh(approval)
        return approval


class AgentToolGateway:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.settings = get_settings()
        self.catalog = self._load_catalog()

    async def execute(
        self,
        *,
        grant: ManagedToolGrant,
        catalog_version: str,
        operation: str,
        args: dict[str, Any],
        tool_call_id: str,
    ) -> dict[str, Any]:
        if catalog_version != grant.catalog_version or catalog_version != TOOL_CATALOG_VERSION:
            raise ManagedToolExecutorError(
                "CATALOG_VERSION_MISMATCH", "Tool catalog version does not match"
            )
        command = self.catalog.get(operation)
        if command is None:
            raise ManagedToolExecutorError(
                "TOOL_NOT_ALLOWED", "Tool is not registered for the Agent runtime"
            )
        args = self._runtime_bounded_args(operation, args)
        argv = self._argv(operation, args)
        stdin_payload = self._stdin_payload(operation, args)
        requires_approval = command.get("requires_platform_approval") is True
        if requires_approval:
            approval = self._create_approval(
                grant=grant,
                operation=operation,
                args=args,
                tool_call_id=tool_call_id,
            )
            try:
                await self._wait_for_approval(approval.id, grant=grant)
            except BaseException:
                self._cancel_approval(approval.id)
                raise
            if command.get("cli_requires_yes_flag") is True:
                argv.append("--yes")
        self._rotate_credential_if_needed(grant)
        envelope = await self._run_cli(grant=grant, argv=argv, stdin_payload=stdin_payload)
        if requires_approval:
            self._mark_approval_executed(grant, tool_call_id, operation, args)
        return envelope

    def _runtime_bounded_args(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", "Tool arguments are invalid")
        bounded = dict(args)
        if operation not in {"run.wait", "evaluation.wait"}:
            return bounded
        maximum_wait = max(1, self.settings.agent_tool_timeout_seconds - 3)
        bounded["wait_timeout"] = _bounded_number(
            bounded.get("wait_timeout", min(30, maximum_wait)),
            "wait_timeout",
            1,
            maximum_wait,
        )
        return bounded

    @staticmethod
    def _load_catalog() -> dict[str, dict[str, Any]]:
        with CATALOG_PATH.open("r", encoding="utf-8") as source:
            payload = yaml.safe_load(source)
        if payload.get("schema_version") != TOOL_CATALOG_VERSION:
            raise RuntimeError("Tool catalog schema version is unsupported")
        with PI_TOOL_CATALOG_PATH.open("r", encoding="utf-8") as source:
            registered_payload = json.load(source)
        if registered_payload.get("catalog_version") != TOOL_CATALOG_VERSION:
            raise RuntimeError("Pi tool catalog version is unsupported")
        registered = {
            item.get("operation")
            for item in registered_payload.get("tools", [])
            if isinstance(item, dict) and isinstance(item.get("operation"), str)
        }
        catalog = {
            item["id"]: item
            for item in payload.get("commands", [])
            if item.get("id") in registered and item.get("status") == "cli-ready"
        }
        if set(catalog) != registered:
            raise RuntimeError("Registered Pi tools do not match the CLI-ready catalog")
        for operation, command in catalog.items():
            if (
                command.get("exposure") == "agent-confirmation"
                and command.get("requires_platform_approval") is not True
            ):
                raise RuntimeError(f"Registered confirmation tool lacks approval: {operation}")
        return catalog

    @staticmethod
    def _argv(operation: str, args: dict[str, Any]) -> list[str]:
        if operation == "workflow.validate":
            _reject_unknown(args, {"definition"})
            _structured_definition(args.get("definition"))
            return ["workflow", "validate", "--definition", "-"]
        if operation == "workflow.list":
            allowed = {"page", "limit", "sort", "query"}
            _reject_unknown(args, allowed)
            page = _bounded_int(args.get("page", 1), "page", 1, 100_000)
            limit = _bounded_int(args.get("limit", 20), "limit", 1, 200)
            sort = _safe_value(args.get("sort", "updated_at:desc"), "sort")
            argv = ["workflow", "list", "--page", str(page), "--limit", str(limit), "--sort", sort]
            if args.get("query") is not None:
                argv.extend(["--query", _safe_value(args["query"], "query")])
            return argv
        if operation == "workflow.get":
            _reject_unknown(args, {"workflow_id"})
            return ["workflow", "get", _safe_value(args.get("workflow_id"), "workflow_id")]
        if operation == "workflow.create":
            _reject_unknown(args, {"name", "description", "definition"})
            _structured_definition(args.get("definition"))
            argv = ["workflow", "create", "--definition", "-"]
            if args.get("name") is not None:
                argv.extend(["--name", _safe_value(args["name"], "name")])
            if args.get("description") is not None:
                argv.extend(["--description", _safe_value(args["description"], "description")])
            return argv
        if operation == "workflow.update":
            allowed = {
                "workflow_id",
                "name",
                "description",
                "clear_description",
                "definition",
                "base_version",
            }
            _reject_unknown(args, allowed)
            argv = ["workflow", "update", _safe_value(args.get("workflow_id"), "workflow_id")]
            if args.get("name") is not None:
                argv.extend(["--name", _safe_value(args["name"], "name")])
            if args.get("description") is not None:
                argv.extend(["--description", _safe_value(args["description"], "description")])
            if args.get("clear_description") is True:
                argv.append("--clear-description")
            if args.get("definition") is not None:
                _structured_definition(args["definition"])
                argv.extend(["--definition", "-"])
                argv.extend(
                    [
                        "--base-version",
                        str(_bounded_int(args.get("base_version"), "base_version", 1, 1_000_000)),
                    ]
                )
            elif args.get("base_version") is not None:
                raise ManagedToolExecutorError(
                    "TOOL_ARGUMENT_INVALID", "base_version requires definition"
                )
            if len(argv) == 3:
                raise ManagedToolExecutorError(
                    "TOOL_ARGUMENT_INVALID", "At least one workflow update is required"
                )
            return argv
        if operation == "workflow.version.list":
            _reject_unknown(args, {"workflow_id"})
            return [
                "workflow",
                "version",
                "list",
                _safe_value(args.get("workflow_id"), "workflow_id"),
            ]
        if operation == "workflow.version.get":
            _reject_unknown(args, {"workflow_id", "version"})
            return [
                "workflow",
                "version",
                "get",
                _safe_value(args.get("workflow_id"), "workflow_id"),
                str(_bounded_int(args.get("version"), "version", 1, 1_000_000)),
            ]
        if operation == "workflow.execute":
            _reject_unknown(args, {"workflow_id", "version", "file_ids", "run_name"})
            argv = ["workflow", "execute", _safe_value(args.get("workflow_id"), "workflow_id")]
            if args.get("version") is not None:
                argv.extend(
                    ["--version", str(_bounded_int(args["version"], "version", 1, 1_000_000))]
                )
            file_ids = args.get("file_ids", [])
            if not isinstance(file_ids, list) or len(file_ids) > 100:
                raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", "file_ids is invalid")
            for file_id in file_ids:
                argv.extend(["--file-id", _safe_value(file_id, "file_id")])
            if args.get("run_name") is not None:
                argv.extend(["--run-name", _safe_value(args["run_name"], "run_name")])
            return argv
        if operation in {"workflow.publish", "workflow.delete"}:
            _reject_unknown(args, {"workflow_id"})
            return [
                "workflow",
                operation.rsplit(".", 1)[1],
                _safe_value(args.get("workflow_id"), "workflow_id"),
            ]
        if operation == "workflow.version.restore":
            _reject_unknown(args, {"workflow_id", "version"})
            return [
                "workflow",
                "version",
                "restore",
                _safe_value(args.get("workflow_id"), "workflow_id"),
                str(_bounded_int(args.get("version"), "version", 1, 1_000_000)),
            ]
        if operation in {"workflow.draft-run", "workflow.node-run"}:
            allowed = {"definition", "file_ids", "run_name"}
            if operation == "workflow.node-run":
                allowed = {"definition", "node_id", "file_ids"}
            _reject_unknown(args, allowed)
            _structured_definition(args.get("definition"))
            command = operation.rsplit(".", 1)[1]
            argv = ["workflow", command, "--definition", "-"]
            if operation == "workflow.node-run":
                argv.extend(["--node-id", _safe_value(args.get("node_id"), "node_id")])
            for file_id in _safe_string_list(args.get("file_ids", []), "file_ids", maximum=100):
                argv.extend(["--file-id", file_id])
            if operation == "workflow.draft-run" and args.get("run_name") is not None:
                argv.extend(["--run-name", _safe_value(args["run_name"], "run_name")])
            return argv
        if operation == "run.list":
            _reject_unknown(args, {"page", "limit", "status", "workflow_id"})
            argv = [
                "run",
                "list",
                "--page",
                str(_bounded_int(args.get("page", 1), "page", 1, 100_000)),
                "--limit",
                str(_bounded_int(args.get("limit", 20), "limit", 1, 200)),
                "--status",
                _safe_value(args.get("status", "all"), "status"),
            ]
            if args.get("workflow_id") is not None:
                argv.extend(["--workflow-id", _safe_value(args["workflow_id"], "workflow_id")])
            return argv
        if operation in {"run.get", "run.results", "run.cancel", "run.retry"}:
            _reject_unknown(args, {"run_id"})
            return ["run", operation.rsplit(".", 1)[1], _safe_value(args.get("run_id"), "run_id")]
        if operation == "run.wait":
            _reject_unknown(args, {"run_id", "wait_timeout", "interval"})
            return [
                "run",
                "wait",
                _safe_value(args.get("run_id"), "run_id"),
                "--wait-timeout",
                _number_text(_bounded_number(args.get("wait_timeout", 30), "wait_timeout", 1, 297)),
                "--interval",
                _number_text(_bounded_number(args.get("interval", 2), "interval", 0.1, 60)),
            ]
        if operation == "run.node.get":
            _reject_unknown(args, {"run_id", "node_id"})
            return [
                "run",
                "node",
                "get",
                _safe_value(args.get("run_id"), "run_id"),
                _safe_value(args.get("node_id"), "node_id"),
            ]
        if operation == "file.list":
            _reject_unknown(args, {"page", "limit", "query"})
            argv = [
                "file",
                "list",
                "--page",
                str(_bounded_int(args.get("page", 1), "page", 1, 100_000)),
                "--limit",
                str(_bounded_int(args.get("limit", 50), "limit", 1, 200)),
            ]
            if args.get("query") is not None:
                argv.extend(["--query", _safe_value(args["query"], "query")])
            return argv
        if operation == "file.get":
            _reject_unknown(args, {"file_id"})
            return ["file", "get", _safe_value(args.get("file_id"), "file_id")]
        if operation == "test-set.list":
            _reject_unknown(args, set())
            return ["test-set", "list"]
        if operation == "test-set.get":
            _reject_unknown(args, {"test_set_id"})
            return ["test-set", "get", _safe_value(args.get("test_set_id"), "test_set_id")]
        if operation in {"test-set.document.list", "test-set.document.get"}:
            allowed = {"test_set_id"}
            if operation.endswith(".get"):
                allowed.add("document_id")
            _reject_unknown(args, allowed)
            argv = [
                "test-set",
                "document",
                operation.rsplit(".", 1)[1],
                _safe_value(args.get("test_set_id"), "test_set_id"),
            ]
            if operation.endswith(".get"):
                argv.append(_safe_value(args.get("document_id"), "document_id"))
            return argv
        if operation in {
            "ground-truth.get",
            "ground-truth.version.list",
            "ground-truth.version.get",
        }:
            allowed = {"test_set_id", "document_id"}
            if operation.endswith(".version.get"):
                allowed.add("version")
            _reject_unknown(args, allowed)
            argv = ["ground-truth"]
            if operation == "ground-truth.get":
                argv.append("get")
            else:
                argv.extend(["version", operation.rsplit(".", 1)[1]])
            argv.extend(
                [
                    _safe_value(args.get("test_set_id"), "test_set_id"),
                    _safe_value(args.get("document_id"), "document_id"),
                ]
            )
            if operation.endswith(".version.get"):
                argv.append(str(_bounded_int(args.get("version"), "version", 1, 1_000_000)))
            return argv
        if operation == "evaluation.list":
            _reject_unknown(args, {"test_set_id"})
            return ["evaluation", "list", _safe_value(args.get("test_set_id"), "test_set_id")]
        if operation in {"evaluation.get", "evaluation.results", "evaluation.cancel"}:
            _reject_unknown(args, {"evaluation_id"})
            return [
                "evaluation",
                operation.rsplit(".", 1)[1],
                _safe_value(args.get("evaluation_id"), "evaluation_id"),
            ]
        if operation == "evaluation.wait":
            _reject_unknown(args, {"evaluation_id", "wait_timeout", "interval"})
            return [
                "evaluation",
                "wait",
                _safe_value(args.get("evaluation_id"), "evaluation_id"),
                "--wait-timeout",
                _number_text(_bounded_number(args.get("wait_timeout", 30), "wait_timeout", 1, 297)),
                "--interval",
                _number_text(_bounded_number(args.get("interval", 2), "interval", 0.1, 60)),
            ]
        if operation in {"evaluation.result", "evaluation.comparison.get"}:
            _reject_unknown(args, {"evaluation_id", "result_id"})
            argv = ["evaluation"]
            if operation == "evaluation.result":
                argv.append("result")
            else:
                argv.extend(["comparison", "get"])
            argv.extend(
                [
                    _safe_value(args.get("evaluation_id"), "evaluation_id"),
                    _safe_value(args.get("result_id"), "result_id"),
                ]
            )
            return argv
        if operation == "evaluation.create":
            _reject_unknown(
                args,
                {"test_set_id", "workflow_id", "name", "document_ids", "client_request_id"},
            )
            argv = [
                "evaluation",
                "create",
                _safe_value(args.get("test_set_id"), "test_set_id"),
                "--workflow-id",
                _safe_value(args.get("workflow_id"), "workflow_id"),
            ]
            if args.get("name") is not None:
                argv.extend(["--name", _safe_value(args["name"], "name")])
            for document_id in _safe_string_list(
                args.get("document_ids", []), "document_ids", maximum=1000
            ):
                argv.extend(["--document-id", document_id])
            if args.get("client_request_id") is not None:
                argv.extend(
                    [
                        "--client-request-id",
                        _safe_value(args["client_request_id"], "client_request_id"),
                    ]
                )
            return argv
        if operation == "provider.list":
            _reject_unknown(args, {"category", "provider_type", "all"})
            argv = ["provider", "list"]
            if args.get("category") is not None:
                argv.extend(["--category", _safe_value(args["category"], "category")])
            if args.get("provider_type") is not None:
                argv.extend(
                    ["--provider-type", _safe_value(args["provider_type"], "provider_type")]
                )
            if args.get("all", False) is True:
                argv.append("--all")
            elif args.get("all", False) is not False:
                raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", "all must be a boolean")
            return argv
        if operation == "provider.get":
            _reject_unknown(args, {"provider_id"})
            return ["provider", "get", _safe_value(args.get("provider_id"), "provider_id")]
        if operation == "provider.model.list":
            _reject_unknown(args, {"category"})
            argv = ["provider", "model", "list"]
            if args.get("category") is not None:
                argv.extend(["--category", _safe_value(args["category"], "category")])
            return argv
        if operation == "node-type.list":
            _reject_unknown(args, set())
            return ["node-type", "list"]
        raise ManagedToolExecutorError("TOOL_NOT_ALLOWED", "Tool is not registered")

    @staticmethod
    def _stdin_payload(operation: str, args: dict[str, Any]) -> bytes | None:
        if operation in {
            "workflow.validate",
            "workflow.create",
            "workflow.update",
            "workflow.draft-run",
            "workflow.node-run",
        }:
            definition = args.get("definition")
            if definition is None and operation == "workflow.update":
                return None
            return json.dumps(
                _structured_definition(definition),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        return None

    def _create_approval(
        self,
        *,
        grant: ManagedToolGrant,
        operation: str,
        args: dict[str, Any],
        tool_call_id: str,
    ) -> ToolApprovalRequest:
        canonical = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        now = utcnow_naive()
        approval = ToolApprovalRequest(
            id=f"tap_{secrets.token_urlsafe(18)}",
            user_id=grant.user_id,
            workspace_id=grant.workspace_id,
            agent_session_id=grant.agent_session_id,
            runtime_generation=grant.runtime_generation,
            tool_call_id=_safe_value(tool_call_id, "tool_call_id"),
            operation=operation,
            argument_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            argument_summary=canonical[:2_000],
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.agent_tool_approval_ttl_seconds),
        )
        with SessionLocal() as database:
            database.add(approval)
            database.commit()
            database.refresh(approval)
        return approval

    async def _wait_for_approval(self, approval_id: str, *, grant: ManagedToolGrant) -> None:
        while True:
            with SessionLocal() as database:
                approval = database.get(ToolApprovalRequest, approval_id)
                session = database.get(ChatboxSession, grant.agent_session_id)
                now = utcnow_naive()
                if approval is None:
                    raise ManagedToolExecutorError("APPROVAL_MISSING", "Tool approval disappeared")
                if (
                    session is None
                    or session.session_state != "active"
                    or session.runtime_generation != grant.runtime_generation
                ):
                    raise ManagedToolExecutorError(
                        "APPROVAL_STALE", "Agent Session changed before approval"
                    )
                if approval.expires_at <= now:
                    approval.status = "expired"
                    approval.decided_at = now
                    database.commit()
                    raise ManagedToolExecutorError("APPROVAL_EXPIRED", "Tool approval expired")
                if approval.status == "approved":
                    return
                if approval.status in {"rejected", "cancelled", "expired"}:
                    raise ManagedToolExecutorError(
                        "APPROVAL_REJECTED", "Tool execution was not approved"
                    )
            await asyncio.sleep(_APPROVAL_POLL_SECONDS)

    @staticmethod
    def _cancel_approval(approval_id: str) -> None:
        now = utcnow_naive()
        with SessionLocal() as database:
            approval = database.get(ToolApprovalRequest, approval_id)
            if approval is not None and approval.status in {"pending", "approved"}:
                approval.status = "cancelled"
                approval.decided_at = now
                database.commit()

    @staticmethod
    def _mark_approval_executed(
        grant: ManagedToolGrant,
        tool_call_id: str,
        operation: str,
        args: dict[str, Any],
    ) -> None:
        digest = hashlib.sha256(
            json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        with SessionLocal() as database:
            approval = database.scalar(
                select(ToolApprovalRequest)
                .where(
                    ToolApprovalRequest.agent_session_id == grant.agent_session_id,
                    ToolApprovalRequest.runtime_generation == grant.runtime_generation,
                    ToolApprovalRequest.tool_call_id == tool_call_id,
                    ToolApprovalRequest.operation == operation,
                    ToolApprovalRequest.argument_digest == digest,
                    ToolApprovalRequest.status == "approved",
                )
                .order_by(ToolApprovalRequest.created_at.desc())
            )
            if approval is not None:
                approval.status = "executed"
                database.commit()

    @staticmethod
    def _rotate_credential_if_needed(grant: ManagedToolGrant) -> None:
        if grant.credential.record.expires_at > utcnow_naive() + timedelta(
            seconds=_ROTATE_BEFORE_SECONDS
        ):
            return
        grant.credential = AgentSessionCredentialService().issue(
            agent_session_id=grant.agent_session_id,
            user_id=grant.user_id,
            workspace_id=grant.workspace_id,
            runtime_generation=grant.runtime_generation,
        )

    async def _run_cli(
        self,
        *,
        grant: ManagedToolGrant,
        argv: list[str],
        stdin_payload: bytes | None = None,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(
            prefix="pressroom-agent-", dir=self.settings.temp_dir
        ) as temp:
            token_path = Path(temp) / "token"
            token_path.write_text(grant.credential.raw_token, encoding="utf-8")
            token_path.chmod(0o600)
            workspace_root = (
                Path(self.settings.storage_root).resolve() / "workspaces" / grant.workspace_id
            )
            env = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    item
                    for item in (str(CLI_SOURCE_ROOT), os.environ.get("PYTHONPATH", ""))
                    if item
                ),
                "PRESSROOM_HOST": self.settings.chatbox_internal_proxy_base_url.rstrip("/"),
                "PRESSROOM_WORKSPACE_ID": grant.workspace_id,
                "PRESSROOM_AGENT_SESSION_ID": grant.agent_session_id,
                "PRESSROOM_TOKEN_FILE": str(token_path),
                "PRESSROOM_ALLOWED_FILE_ROOTS": str(workspace_root),
                "PRESSROOM_ALLOW_INSECURE_HTTP": "true",
            }
            command = [
                sys.executable,
                "-m",
                "pressroom_cli",
                *argv,
                "--json",
                "--timeout",
                str(self.settings.agent_tool_timeout_seconds),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(workspace_root),
                    env=env,
                    stdin=(
                        asyncio.subprocess.PIPE
                        if stdin_payload is not None
                        else asyncio.subprocess.DEVNULL
                    ),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                raise ManagedToolExecutorError(
                    "TOOL_PROCESS_FAILED", "Tool process could not be started"
                ) from exc
            if stdin_payload is not None:
                assert proc.stdin is not None
                proc.stdin.write(stdin_payload)
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.stdin.wait_closed()
            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.gather(
                        _read_bounded(
                            proc.stdout,
                            limit=self.settings.agent_tool_output_max_bytes,
                            code="TOOL_OUTPUT_LIMIT",
                        ),
                        _read_bounded(
                            proc.stderr,
                            limit=min(self.settings.agent_tool_output_max_bytes, 65_536),
                            code="TOOL_STDERR_LIMIT",
                        ),
                    ),
                    timeout=self.settings.agent_tool_timeout_seconds + 2,
                )
            except asyncio.TimeoutError as exc:
                await _terminate_process(proc)
                raise ManagedToolExecutorError("TOOL_TIMEOUT", "Tool execution timed out") from exc
            except asyncio.CancelledError:
                await _terminate_process(proc)
                raise
            except ManagedToolExecutorError:
                await _terminate_process(proc)
                raise
            await proc.wait()
            if proc.returncode is None:
                raise ManagedToolExecutorError("TOOL_PROCESS_FAILED", "Tool process did not exit")
            try:
                envelope = json.loads(stdout)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Agent Tool Gateway received invalid CLI JSON session=%s "
                    "operation_exit=%s stderr_bytes=%s",
                    grant.agent_session_id,
                    proc.returncode,
                    len(stderr),
                )
                raise ManagedToolExecutorError(
                    "TOOL_INVALID_OUTPUT", "Tool returned invalid output"
                ) from exc
            if (
                not isinstance(envelope, dict)
                or envelope.get("schema_version") != "pressroom-envelope.v1"
            ):
                raise ManagedToolExecutorError(
                    "TOOL_INVALID_OUTPUT", "Tool returned an unsupported envelope"
                )
            logger.info(
                "Agent Tool Gateway completed CLI call session=%s exit=%s ok=%s",
                grant.agent_session_id,
                proc.returncode,
                envelope.get("ok") is True,
            )
            return envelope


def error_envelope(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "pressroom-envelope.v1",
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "details": None},
        "request_id": None,
    }


def _reject_unknown(args: dict[str, Any], allowed: set[str]) -> None:
    if not isinstance(args, dict) or set(args) - allowed:
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", "Tool arguments are invalid")


def _safe_value(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 2_000 or any(char in normalized for char in "\r\n\x00"):
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", f"{label} is invalid")
    return normalized


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", f"{label} is invalid")
    return value


def _bounded_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not minimum <= float(value) <= maximum
    ):
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", f"{label} is invalid")
    return float(value)


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _safe_string_list(value: Any, label: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", f"{label} is invalid")
    return [_safe_value(item, label.removesuffix("s")) for item in value]


def _structured_definition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagedToolExecutorError("TOOL_ARGUMENT_INVALID", "definition must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManagedToolExecutorError(
            "TOOL_ARGUMENT_INVALID", "definition is not valid JSON"
        ) from exc
    if len(encoded) > _MAX_STRUCTURED_INPUT_BYTES:
        raise ManagedToolExecutorError(
            "TOOL_ARGUMENT_INVALID", "definition exceeds the structured input limit"
        )
    return value


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    *,
    limit: int,
    code: str,
) -> bytes:
    if stream is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(min(65_536, limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ManagedToolExecutorError(code, "Tool output exceeded its limit")
        chunks.append(chunk)


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


ManagedToolExecutor = AgentToolGateway
issue_agent_tool_gateway_grant = issue_managed_tool_grant
require_agent_tool_gateway_grant = require_managed_tool_grant
revoke_agent_tool_gateway_grants = revoke_managed_tool_grants
revoke_agent_tool_gateway_grants_for_user = revoke_managed_tool_grants_for_user


__all__ = [
    "AgentToolGateway",
    "AgentToolGatewayError",
    "AgentToolGatewayGrant",
    "ManagedToolExecutor",
    "ManagedToolExecutorError",
    "TOOL_CATALOG_VERSION",
    "_TOOL_GRANT_HEADER",
    "decide_approval",
    "error_envelope",
    "issue_managed_tool_grant",
    "issue_agent_tool_gateway_grant",
    "list_pending_approvals",
    "require_managed_tool_grant",
    "require_agent_tool_gateway_grant",
    "revoke_managed_tool_grants",
    "revoke_managed_tool_grants_for_user",
    "revoke_agent_tool_gateway_grants",
    "revoke_agent_tool_gateway_grants_for_user",
]
