"""Authenticated chatbox session REST and Pi event WebSocket boundary."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import get_auth_service, require_workspace_capability
from app.api.internal_proxy import issue_internal_proxy_grant, revoke_internal_proxy_grants
from app.api.providers import get_provider_store
from app.config import get_settings
from app.db.session import SessionLocal
from app.errors import AppError
from app.models.db.chatbox_session import ChatboxSession
from app.providers.models import ModelProviderRow, ProviderType
from app.providers.store import ProviderStore
from app.services.agent_admission import AgentAdmissionService
from app.services.agent_sessions import AgentSessionService
from app.services.agent_tool_gateway import (
    TOOL_CATALOG_VERSION,
    decide_approval,
    issue_agent_tool_gateway_grant,
    list_pending_approvals,
    revoke_agent_tool_gateway_grants,
)
from app.services.chatbox_broker import (
    BrokerItem,
    ChatboxBrokerBusyError,
    ChatboxBrokerResyncError,
    ChatboxRuntimeBroker,
)
from app.services.pi_runtime import PiRuntimeError, PiRuntimeHandle, get_pi_runtime_launcher
from app.services.workspace_access import ResolvedContext, resolve_workspace_access
from app.services.workspace_rbac import workspace_rbac_enforced

router = APIRouter(prefix="/chatbox/sessions", tags=["chatbox"])
logger = logging.getLogger(__name__)
_PI_CHECKPOINT_SCHEMA_VERSION = 3
_PI_LEGACY_MESSAGE_ROLES = frozenset({"user", "assistant", "toolResult"})

ChatboxCreateContext = Annotated[
    ResolvedContext, Depends(require_workspace_capability("provider.use"))
]
ChatboxViewContext = Annotated[ResolvedContext, Depends(require_workspace_capability("run.view"))]
ProviderStoreDep = Annotated[ProviderStore, Depends(get_provider_store)]


class _ChatboxSessionBusyError(RuntimeError):
    """Raised when another WebSocket currently owns a session's event stream."""


class ChatboxSessionCreateRequest(BaseModel):
    provider_id: str | None = None


class ChatboxSessionResponse(BaseModel):
    session_id: str
    state: str
    provider_id: str
    model_id: str
    messages: list[object] = Field(default_factory=list)
    tool_executions: dict[str, object] = Field(default_factory=dict)
    compaction_notes: list[object] = Field(default_factory=list)
    live_message_id: str | None = None
    snapshot_revision: int = 0
    session_state: str
    runtime_state: str
    runtime_generation: int
    title: str | None = None
    preview: str | None = None
    first_settled_at: datetime | None = None
    last_activity_at: datetime
    archived_at: datetime | None = None
    is_current: bool = False


class ChatboxSessionListResponse(BaseModel):
    items: list[ChatboxSessionResponse] = Field(default_factory=list)
    total: int
    current_session_id: str | None = None


class ToolApprovalResponse(BaseModel):
    id: str
    operation: str
    argument_summary: str
    expires_at: datetime


class ToolApprovalListResponse(BaseModel):
    items: list[ToolApprovalResponse] = Field(default_factory=list)


class ChatboxSessionStopResponse(BaseModel):
    success: bool


def _resolve_provider(
    store: ProviderStore, workspace_id: str, requested_provider_id: str | None
) -> ModelProviderRow:
    providers = store.list_visible(
        workspace_id,
        provider_type=ProviderType.llm_api.value,
    )
    if requested_provider_id is not None:
        provider = next((item for item in providers if item.id == requested_provider_id), None)
        if provider is None:
            raise HTTPException(status_code=404, detail="Chatbot provider not found")
    else:
        provider = next((item for item in providers if item.is_chatbot_default), None)
        if provider is None:
            raise HTTPException(
                status_code=409,
                detail="No workspace chatbot default provider configured",
            )
    if (
        provider.model_id is None
        or provider.api_protocol is None
        or provider.model_context_window is None
        or provider.model_max_tokens is None
        or provider.model_reasoning is None
    ):
        raise HTTPException(status_code=409, detail="Chatbot provider configuration is incomplete")
    return provider


def _session_response(
    session: ChatboxSession,
    provider: ModelProviderRow,
    *,
    is_current: bool = False,
) -> ChatboxSessionResponse:
    """Return the authoritative browser-safe reconnect snapshot."""

    if provider.model_id is None:
        raise HTTPException(status_code=409, detail="Chatbot provider configuration is incomplete")
    return ChatboxSessionResponse(
        session_id=session.id,
        state=session.lifecycle_state,
        provider_id=session.provider_id,
        model_id=provider.model_id,
        messages=list(session.messages_json or []),
        tool_executions=dict(session.tool_executions_json or {}),
        compaction_notes=list(session.compaction_notes_json or []),
        live_message_id=session.live_message_id,
        snapshot_revision=session.snapshot_revision,
        session_state=session.session_state,
        runtime_state=session.runtime_state,
        runtime_generation=session.runtime_generation,
        title=session.title,
        preview=session.preview,
        first_settled_at=session.first_settled_at,
        last_activity_at=session.last_activity_at,
        archived_at=session.archived_at,
        is_current=is_current,
    )


def _get_session(session_id: str, workspace_id: str) -> ChatboxSession:
    with SessionLocal() as database:
        chat_session = database.scalar(
            select(ChatboxSession).where(ChatboxSession.id == session_id)
        )
    if not isinstance(chat_session, ChatboxSession) or chat_session.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    return chat_session


def _authorize_session(chat_session: ChatboxSession, context: ResolvedContext | None) -> None:
    if context is not None and chat_session.user_id != context.user.id:
        raise HTTPException(status_code=404, detail="Chatbox session not found")


def _set_lifecycle(
    session_id: str,
    lifecycle_state: str,
    pi_session_ref: str | None = None,
    runtime_state: str | None = None,
) -> None:
    with SessionLocal() as database:
        chat_session = database.get(ChatboxSession, session_id)
        if chat_session is not None:
            chat_session.lifecycle_state = lifecycle_state
            if pi_session_ref is not None:
                chat_session.pi_session_ref = pi_session_ref
            if runtime_state is not None:
                chat_session.runtime_state = runtime_state
            chat_session.updated_at = datetime.now()
            database.commit()


def _runtime_handles(app: Any) -> dict[str, PiRuntimeHandle]:
    handles: dict[str, PiRuntimeHandle] | None = getattr(
        app.state,
        "chatbox_runtime_handles",
        None,
    )
    if handles is None:
        handles = {}
        app.state.chatbox_runtime_handles = handles
    return handles


def _checkpoint_root() -> Path:
    settings = get_settings()
    if settings.agent_checkpoint_root:
        return Path(settings.agent_checkpoint_root).resolve()
    return Path(settings.storage_root).resolve() / ".agent-sessions"


def _checkpoint_dir(chat_session: ChatboxSession) -> Path:
    directory = _checkpoint_root() / chat_session.workspace_id / chat_session.id
    directory.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    if settings.pi_runtime_service_url and hasattr(os, "chown"):
        os.chown(directory, settings.pi_runtime_uid, settings.pi_runtime_gid)
        directory.chmod(0o700)
    return directory.resolve()


def _checkpoint_digest(candidate: Path, expected: str | None) -> str:
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if expected and not secrets.compare_digest(digest, expected):
        raise PiRuntimeError("Agent Session checkpoint integrity check failed")
    return digest


def _migrate_legacy_checkpoint(
    chat_session: ChatboxSession,
    candidate: Path,
    directory: Path,
) -> Path:
    """Copy a pre-isolation checkpoint into the Runtime-owned volume.

    The compatibility path is deliberately narrow: only the legacy directory
    for this exact workspace and Session is accepted, and the persisted digest
    is verified before any copy. The old file is retained until normal data
    lifecycle cleanup so a failed rollout remains recoverable.
    """
    settings = get_settings()
    legacy_root = (Path(settings.storage_root).resolve() / ".agent-sessions").resolve()
    legacy_directory = (legacy_root / chat_session.workspace_id / chat_session.id).resolve()
    if (
        not legacy_directory.is_relative_to(legacy_root)
        or not candidate.is_relative_to(legacy_directory)
        or not candidate.is_file()
    ):
        raise PiRuntimeError("Agent Session checkpoint is unavailable")

    source_digest = _checkpoint_digest(candidate, chat_session.checkpoint_hash)
    destination = (directory / candidate.name).resolve()
    if not destination.is_relative_to(directory):
        raise PiRuntimeError("Agent Session checkpoint escaped its private boundary")
    if destination.is_file():
        if not secrets.compare_digest(_checkpoint_digest(destination, None), source_digest):
            raise PiRuntimeError("Agent Session checkpoint migration conflict")
        return destination

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".checkpoint-migration-",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            with candidate.open("rb") as source:
                shutil.copyfileobj(source, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        if not secrets.compare_digest(_checkpoint_digest(temporary_path, None), source_digest):
            raise PiRuntimeError("Agent Session checkpoint migration integrity check failed")
        if settings.pi_runtime_service_url and hasattr(os, "chown"):
            os.chown(temporary_path, settings.pi_runtime_uid, settings.pi_runtime_gid)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return destination


def _validated_checkpoint_path(chat_session: ChatboxSession) -> Path | None:
    if chat_session.checkpoint_ref is None:
        return None
    if chat_session.checkpoint_schema_version != _PI_CHECKPOINT_SCHEMA_VERSION:
        raise PiRuntimeError("Agent Session checkpoint schema is incompatible")
    candidate = Path(chat_session.checkpoint_ref).resolve()
    directory = _checkpoint_dir(chat_session)
    if not candidate.is_relative_to(directory):
        candidate = _migrate_legacy_checkpoint(chat_session, candidate, directory)
    if not candidate.is_file():
        raise PiRuntimeError("Agent Session checkpoint is unavailable")
    _checkpoint_digest(candidate, chat_session.checkpoint_hash)
    return candidate


def _record_runtime_checkpoint(
    chat_session_id: str,
    handle: PiRuntimeHandle,
    *,
    allow_missing: bool = False,
) -> None:
    checkpoint_path = handle.checkpoint_path
    if checkpoint_path is None:
        raise PiRuntimeError("Agent Session checkpoint is unavailable")
    if not checkpoint_path.is_file():
        # Pi reserves the durable path during startup but does not create the
        # JSONL file until the first conversation entry is persisted. An empty
        # draft Session can therefore start or stop without a checkpoint yet;
        # settled and resumed Sessions continue to fail closed below.
        if allow_missing:
            return
        raise PiRuntimeError("Agent Session checkpoint is unavailable")
    digest = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    with SessionLocal() as database:
        session = database.get(ChatboxSession, chat_session_id)
        if session is None or session.runtime_generation != handle.runtime_generation:
            raise PiRuntimeError("Agent Session generation changed before checkpoint")
        session.checkpoint_ref = str(checkpoint_path)
        session.checkpoint_hash = digest
        session.checkpoint_schema_version = (
            handle.checkpoint_schema_version or _PI_CHECKPOINT_SCHEMA_VERSION
        )
        session.checkpoint_revision += 1
        session.updated_at = datetime.now()
        database.commit()


def _runtime_brokers(app: Any) -> dict[str, ChatboxRuntimeBroker]:
    brokers: dict[str, ChatboxRuntimeBroker] | None = getattr(
        app.state,
        "chatbox_runtime_brokers",
        None,
    )
    if brokers is None:
        brokers = {}
        app.state.chatbox_runtime_brokers = brokers
    return brokers


@dataclass(slots=True)
class _RuntimeLockEntry:
    lock: asyncio.Lock
    users: int = 0


def _runtime_locks(app: Any) -> dict[str, _RuntimeLockEntry]:
    locks: dict[str, _RuntimeLockEntry] | None = getattr(
        app.state,
        "chatbox_runtime_locks",
        None,
    )
    if locks is None:
        locks = {}
        app.state.chatbox_runtime_locks = locks
    return locks


@asynccontextmanager
async def _runtime_lock(app: Any, session_id: str) -> AsyncIterator[None]:
    """Serialize one session and remove its lock after the final user exits."""

    locks = _runtime_locks(app)
    entry = locks.get(session_id)
    if entry is None:
        entry = _RuntimeLockEntry(lock=asyncio.Lock())
        locks[session_id] = entry
    entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.users -= 1
        # Lock release and bookkeeping contain no await, so a waiter cannot
        # acquire the old lock between the final-user check and removal.
        if entry.users == 0 and locks.get(session_id) is entry:
            locks.pop(session_id)


def _active_websocket_sessions(app: Any) -> set[str]:
    sessions: set[str] | None = getattr(
        app.state,
        "chatbox_active_websocket_sessions",
        None,
    )
    if sessions is None:
        sessions = set()
        app.state.chatbox_active_websocket_sessions = sessions
    return sessions


def _create_session_record(*, workspace_id: str, user_id: str, provider_id: str) -> ChatboxSession:
    return AgentSessionService().create_draft(
        workspace_id=workspace_id,
        user_id=user_id,
        provider_id=provider_id,
    )


async def _stop_session_runtime(
    app: Any,
    session_id: str,
    *,
    lifecycle_state: str = "idle",
    release_websocket: bool = True,
) -> None:
    async with _runtime_lock(app, session_id):
        broker = _runtime_brokers(app).pop(session_id, None)
        runtime = _runtime_handles(app).pop(session_id, None)
        # Revoke authority before process/checkpoint I/O so a concurrent stale
        # tool request cannot continue during a slow shutdown.
        revoke_internal_proxy_grants(app, chatbox_session_id=session_id)
        revoke_agent_tool_gateway_grants(app, agent_session_id=session_id)
        try:
            if broker is not None:
                await broker.stop()
            if runtime is not None:
                await get_pi_runtime_launcher(app).stop_session(runtime.session_id)
                await asyncio.to_thread(
                    _record_runtime_checkpoint,
                    session_id,
                    runtime,
                    allow_missing=True,
                )
        finally:
            if release_websocket:
                _active_websocket_sessions(app).discard(session_id)
            _set_lifecycle(
                session_id,
                lifecycle_state,
                runtime_state="failed" if lifecycle_state == "dead" else "stopped",
            )


async def _release_websocket_session(app: Any, session_id: str) -> None:
    """Release the event-consumer lease while preserving the live Pi session."""

    async with _runtime_lock(app, session_id):
        _active_websocket_sessions(app).discard(session_id)


@router.get("", response_model=ChatboxSessionListResponse)
async def list_chatbox_sessions(
    context: ChatboxViewContext,
    store: ProviderStoreDep,
    view: Literal["conversations", "archived", "all"] = "conversations",
    include_archived: bool | None = None,
) -> ChatboxSessionListResponse:
    """List the signed-in user's sessions in the active workspace."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    service = AgentSessionService()
    current = service.current(user_id=context.user.id, workspace_id=context.workspace_id)
    sessions = service.list_for_user_workspace(
        user_id=context.user.id,
        workspace_id=context.workspace_id,
        view="all" if include_archived else view,
    )
    items = [
        _session_response(
            session,
            _resolve_provider(store, context.workspace_id, session.provider_id),
            is_current=current is not None and current.id == session.id,
        )
        for session in sessions
    ]
    return ChatboxSessionListResponse(
        items=items,
        total=len(items),
        current_session_id=current.id if current is not None else None,
    )


@router.get("/current", response_model=ChatboxSessionResponse | None)
async def get_current_chatbox_session(
    context: ChatboxViewContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse | None:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    session = AgentSessionService().current(
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    if session is None:
        return None
    return _session_response(
        session,
        _resolve_provider(store, context.workspace_id, session.provider_id),
        is_current=True,
    )


@router.post("", response_model=ChatboxSessionResponse, status_code=201)
async def create_chatbox_session(
    request: Request,
    context: ChatboxCreateContext,
    store: ProviderStoreDep,
    payload: ChatboxSessionCreateRequest | None = None,
) -> ChatboxSessionResponse:
    """Create a workspace-scoped durable shell for one Pi runtime session."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    provider = _resolve_provider(
        store,
        context.workspace_id,
        payload.provider_id if payload is not None else None,
    )
    service = AgentSessionService()
    previous = service.current(user_id=context.user.id, workspace_id=context.workspace_id)
    chat_session = _create_session_record(
        workspace_id=context.workspace_id,
        user_id=context.user.id,
        provider_id=provider.id,
    )
    if previous is not None:
        await _stop_session_runtime(request.app, previous.id)
    activated = service.activate(
        session_id=chat_session.id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    ).session
    return _session_response(activated, provider, is_current=True)


@router.get("/{session_id}", response_model=ChatboxSessionResponse)
async def get_chatbox_session(
    session_id: str,
    context: ChatboxViewContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    """Return authoritative durable state and projected history for reconnect."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    chat_session = _get_session(session_id, context.workspace_id)
    _authorize_session(chat_session, context)
    provider = _resolve_provider(store, context.workspace_id, chat_session.provider_id)
    current = AgentSessionService().current(
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    return _session_response(
        chat_session,
        provider,
        is_current=current is not None and current.id == chat_session.id,
    )


@router.delete("/{session_id}", response_model=ChatboxSessionStopResponse)
async def delete_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxViewContext,
) -> ChatboxSessionStopResponse:
    """Permanently delete an archived Agent Session."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    chat_session = _get_session(session_id, context.workspace_id)
    _authorize_session(chat_session, context)
    if chat_session.session_state != "archived":
        raise HTTPException(status_code=409, detail="Only archived conversations can be deleted")
    await _stop_session_runtime(request.app, session_id)
    try:
        AgentSessionService().delete_archived(
            session_id=session_id,
            user_id=context.user.id,
            workspace_id=context.workspace_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    checkpoint_directory = (_checkpoint_root() / context.workspace_id / session_id).resolve()
    if checkpoint_directory.is_relative_to(_checkpoint_root()) and checkpoint_directory.is_dir():
        await asyncio.to_thread(shutil.rmtree, checkpoint_directory)
    return ChatboxSessionStopResponse(success=True)


@router.post("/{session_id}/restart", response_model=ChatboxSessionResponse, status_code=201)
async def restart_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxCreateContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    """Compatibility alias for create-and-activate using the same Provider."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    previous = _get_session(session_id, context.workspace_id)
    _authorize_session(previous, context)
    provider = _resolve_provider(store, context.workspace_id, previous.provider_id)

    await _stop_session_runtime(request.app, session_id)

    restarted = _create_session_record(
        workspace_id=previous.workspace_id,
        user_id=previous.user_id,
        provider_id=previous.provider_id,
    )
    activated = (
        AgentSessionService()
        .activate(
            session_id=restarted.id,
            user_id=context.user.id,
            workspace_id=context.workspace_id,
        )
        .session
    )
    return _session_response(activated, provider, is_current=True)


@router.post("/{session_id}/activate", response_model=ChatboxSessionResponse)
async def activate_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxCreateContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    target = _get_session(session_id, context.workspace_id)
    _authorize_session(target, context)
    if target.session_state == "archived":
        raise HTTPException(status_code=409, detail="Chatbox session is archived")
    current = AgentSessionService().current(
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    if current is not None and current.id != target.id:
        if current.runtime_state == "running":
            raise HTTPException(status_code=409, detail="Wait for the current Agent turn to settle")
        await _stop_session_runtime(request.app, current.id)
    activation = AgentSessionService().activate(
        session_id=target.id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    provider = _resolve_provider(store, context.workspace_id, activation.session.provider_id)
    return _session_response(activation.session, provider, is_current=True)


@router.post("/{session_id}/pause", response_model=ChatboxSessionResponse)
async def pause_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxViewContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    if session.runtime_state == "running":
        raise HTTPException(status_code=409, detail="Abort or wait for the Agent turn to settle")
    await _stop_session_runtime(request.app, session_id)
    paused = AgentSessionService().pause(
        session_id=session_id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    return _session_response(
        paused,
        _resolve_provider(store, context.workspace_id, paused.provider_id),
    )


@router.post("/{session_id}/suspend", response_model=ChatboxSessionResponse)
async def suspend_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxViewContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    """Stop runtime/credentials on workspace switch while retaining selection."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    if session.runtime_state == "running":
        raise HTTPException(status_code=409, detail="Abort or wait for the Agent turn to settle")
    await _stop_session_runtime(request.app, session_id)
    refreshed = AgentSessionService().suspend(
        session_id=session_id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    return _session_response(
        refreshed,
        _resolve_provider(store, context.workspace_id, refreshed.provider_id),
        is_current=True,
    )


@router.post("/{session_id}/archive", response_model=ChatboxSessionResponse)
async def archive_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxViewContext,
    store: ProviderStoreDep,
) -> ChatboxSessionResponse:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    if session.runtime_state == "running":
        raise HTTPException(status_code=409, detail="Abort or wait for the Agent turn to settle")
    await _stop_session_runtime(request.app, session_id)
    archived = AgentSessionService().archive(
        session_id=session_id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    return _session_response(
        archived,
        _resolve_provider(store, context.workspace_id, archived.provider_id),
    )


@router.post("/{session_id}/unarchive", response_model=ChatboxSessionResponse)
async def unarchive_chatbox_session(
    session_id: str,
    request: Request,
    context: ChatboxCreateContext,
    store: ProviderStoreDep,
    activate: bool = False,
) -> ChatboxSessionResponse:
    """Return an archived conversation to paused, optionally opening it."""

    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    current = None
    if activate:
        current = AgentSessionService().current(
            user_id=context.user.id,
            workspace_id=context.workspace_id,
        )
        if current is not None and current.id != session.id:
            if current.runtime_state == "running":
                raise HTTPException(
                    status_code=409,
                    detail="Wait for the current Agent turn to settle",
                )
            await _stop_session_runtime(request.app, current.id)
    try:
        restored = AgentSessionService().unarchive(
            session_id=session_id,
            user_id=context.user.id,
            workspace_id=context.workspace_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if activate:
        restored = (
            AgentSessionService()
            .activate(
                session_id=restored.id,
                user_id=context.user.id,
                workspace_id=context.workspace_id,
            )
            .session
        )
    return _session_response(
        restored,
        _resolve_provider(store, context.workspace_id, restored.provider_id),
        is_current=activate,
    )


@router.get("/{session_id}/approvals", response_model=ToolApprovalListResponse)
async def get_tool_approvals(
    session_id: str,
    context: ChatboxViewContext,
) -> ToolApprovalListResponse:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Chatbox session not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    approvals = list_pending_approvals(
        agent_session_id=session_id,
        user_id=context.user.id,
        workspace_id=context.workspace_id,
    )
    return ToolApprovalListResponse(
        items=[
            ToolApprovalResponse(
                id=item.id,
                operation=item.operation,
                argument_summary=item.argument_summary,
                expires_at=item.expires_at,
            )
            for item in approvals
        ]
    )


@router.post("/{session_id}/approvals/{approval_id}/approve", response_model=ToolApprovalResponse)
@router.post("/{session_id}/approvals/{approval_id}/reject", response_model=ToolApprovalResponse)
async def decide_tool_approval(
    session_id: str,
    approval_id: str,
    request: Request,
    context: ChatboxViewContext,
) -> ToolApprovalResponse:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Tool approval not found")
    session = _get_session(session_id, context.workspace_id)
    _authorize_session(session, context)
    approved = request.url.path.endswith("/approve")
    try:
        approval = decide_approval(
            approval_id=approval_id,
            agent_session_id=session_id,
            user_id=context.user.id,
            workspace_id=context.workspace_id,
            approved=approved,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Tool approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Tool approval is no longer pending") from exc
    return ToolApprovalResponse(
        id=approval.id,
        operation=approval.operation,
        argument_summary=approval.argument_summary,
        expires_at=approval.expires_at,
    )


async def _ws_context(websocket: WebSocket) -> ResolvedContext | None:
    if not workspace_rbac_enforced():
        return None
    try:
        auth = get_auth_service().require_authenticated(
            websocket.cookies.get(get_settings().auth_session_cookie_name)
        )
    except AppError:
        await websocket.close(code=1008)
        return None
    with SessionLocal() as database:
        selector = (
            websocket.query_params.get("workspace_id")
            or websocket.headers.get("X-Workspace-Id")
            or auth.workspace_id
        )
        context = resolve_workspace_access(
            database, context=auth, selector=selector, capability="run.view"
        )
    return context


async def _runtime_for_session(
    websocket: WebSocket,
    chat_session: ChatboxSession,
    provider: ModelProviderRow,
) -> PiRuntimeHandle:
    async with _runtime_lock(websocket.app, chat_session.id):
        return await _runtime_for_session_locked(websocket, chat_session, provider)


async def _claim_runtime_for_session(
    websocket: WebSocket,
    chat_session: ChatboxSession,
    provider: ModelProviderRow,
) -> PiRuntimeHandle:
    """Atomically claim the sole event consumer and start or reuse its runtime."""

    async with _runtime_lock(websocket.app, chat_session.id):
        active_sessions = _active_websocket_sessions(websocket.app)
        if chat_session.id in active_sessions:
            raise _ChatboxSessionBusyError
        active_sessions.add(chat_session.id)
        try:
            return await _runtime_for_session_locked(websocket, chat_session, provider)
        except BaseException:
            active_sessions.discard(chat_session.id)
            raise


async def _claim_chatbox_subscription(
    websocket: WebSocket,
    chat_session: ChatboxSession,
    provider: ModelProviderRow,
    after_revision: int,
) -> tuple[PiRuntimeHandle, ChatboxRuntimeBroker, asyncio.Queue[BrokerItem]]:
    """Atomically claim the runtime, broker, and revision subscription."""

    async with _runtime_lock(websocket.app, chat_session.id):
        active_sessions = _active_websocket_sessions(websocket.app)
        if chat_session.id in active_sessions:
            raise _ChatboxSessionBusyError
        brokers = _runtime_brokers(websocket.app)
        broker = brokers.get(chat_session.id)
        if broker is None and after_revision != chat_session.snapshot_revision:
            # A fresh process has no in-memory journal. Validate the client's
            # durable checkpoint before starting a Node child or issuing its
            # short-lived internal proxy grant.
            raise ChatboxBrokerResyncError
        active_sessions.add(chat_session.id)
        subscriber: asyncio.Queue[BrokerItem] | None = None
        try:
            runtime = await _runtime_for_session_locked(websocket, chat_session, provider)
            if broker is None or broker.runtime is not runtime:
                if broker is not None:
                    await broker.stop()
                workspace_root = (
                    Path(get_settings().storage_root).resolve()
                    / "workspaces"
                    / chat_session.workspace_id
                )

                async def stop_terminal_runtime(failed: bool) -> None:
                    await _stop_session_runtime(
                        websocket.app,
                        chat_session.id,
                        lifecycle_state="dead" if failed else "idle",
                        release_websocket=True,
                    )
                    if not failed:
                        await asyncio.to_thread(
                            AgentSessionService().suspend,
                            session_id=chat_session.id,
                            user_id=chat_session.user_id,
                            workspace_id=chat_session.workspace_id,
                        )

                async def record_checkpoint() -> None:
                    await asyncio.to_thread(
                        _record_runtime_checkpoint,
                        chat_session.id,
                        runtime,
                    )

                broker = ChatboxRuntimeBroker(
                    chatbox_session_id=chat_session.id,
                    runtime=runtime,
                    workspace_root=workspace_root,
                    on_terminal=stop_terminal_runtime,
                    on_checkpoint=record_checkpoint,
                )
                brokers[chat_session.id] = broker
            subscriber = await broker.subscribe(after_revision)
            broker.start()
            return runtime, broker, subscriber
        except BaseException:
            if broker is not None:
                await broker.unsubscribe(subscriber)
            active_sessions.discard(chat_session.id)
            raise


async def _runtime_for_session_locked(
    websocket: WebSocket,
    chat_session: ChatboxSession,
    provider: ModelProviderRow,
) -> PiRuntimeHandle:
    handles = _runtime_handles(websocket.app)
    handle = handles.get(chat_session.id)
    if handle is not None and handle.state != "dead":
        return handle
    if handle is not None:
        raise PiRuntimeError(f"pi runtime session {handle.session_id} is dead")
    if chat_session.session_state != "active":
        raise PiRuntimeError("Agent Session must be activated before starting its runtime")
    if provider.model_id is None or provider.api_protocol is None:
        raise HTTPException(
            status_code=409,
            detail="Chatbot provider configuration is incomplete",
        )
    model_id = provider.model_id
    api_protocol = provider.api_protocol
    model_context_window = provider.model_context_window
    model_max_tokens = provider.model_max_tokens
    model_reasoning = provider.model_reasoning
    assert model_context_window is not None
    assert model_max_tokens is not None
    assert model_reasoning is not None
    workspace_root = (
        Path(get_settings().storage_root).resolve() / "workspaces" / chat_session.workspace_id
    )
    workspace_root.mkdir(parents=True, exist_ok=True)
    proxy_url = (
        f"{get_settings().chatbox_internal_proxy_base_url.rstrip('/')}"
        f"/internal/proxy/invoke/{provider.id}"
    )
    checkpoint_dir = _checkpoint_dir(chat_session)
    checkpoint_path = _validated_checkpoint_path(chat_session)
    legacy_messages = (
        _runtime_legacy_messages(chat_session.messages_json) if checkpoint_path is None else None
    )
    revoke_internal_proxy_grants(websocket.app, chatbox_session_id=chat_session.id)
    revoke_agent_tool_gateway_grants(websocket.app, agent_session_id=chat_session.id)
    proxy_token = issue_internal_proxy_grant(
        websocket.app,
        chatbox_session_id=chat_session.id,
        workspace_id=chat_session.workspace_id,
        provider_id=provider.id,
    )
    tool_grant = issue_agent_tool_gateway_grant(
        websocket.app,
        agent_session_id=chat_session.id,
        user_id=chat_session.user_id,
        workspace_id=chat_session.workspace_id,
        runtime_generation=chat_session.runtime_generation,
    )
    try:
        handle = await get_pi_runtime_launcher(websocket.app).start_session(
            provider_id=provider.id,
            model_id=model_id,
            model_context_window=model_context_window,
            model_max_tokens=model_max_tokens,
            model_reasoning=model_reasoning,
            api_protocol=api_protocol.value,
            proxy_url=proxy_url,
            proxy_token=proxy_token,
            workspace_root=workspace_root,
            agent_session_id=chat_session.id,
            runtime_generation=chat_session.runtime_generation,
            checkpoint_dir=checkpoint_dir,
            checkpoint_path=checkpoint_path,
            legacy_messages=legacy_messages,
            tool_gateway_url=(
                f"{get_settings().chatbox_internal_proxy_base_url.rstrip('/')}"
                "/internal/agent-tools/execute"
            ),
            tool_gateway_grant=tool_grant,
            tool_catalog_version=TOOL_CATALOG_VERSION,
        )
    except BaseException:
        revoke_internal_proxy_grants(websocket.app, chatbox_session_id=chat_session.id)
        revoke_agent_tool_gateway_grants(websocket.app, agent_session_id=chat_session.id)
        raise
    handles[chat_session.id] = handle
    await asyncio.to_thread(
        _record_runtime_checkpoint,
        chat_session.id,
        handle,
        allow_missing=True,
    )
    _set_lifecycle(
        chat_session.id,
        "idle",
        handle.session_id,
        runtime_state="idle",
    )
    return handle


def _runtime_legacy_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Return only Pi-compatible context from the browser conversation snapshot.

    Admission decisions are durable UI history, not model turns. Replaying the
    platform message (or its rejected user prompt) would either violate Pi's
    message-role contract or make the model answer a request that Admission
    explicitly rejected.
    """

    result: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        message_id = message.get("id")
        if role not in _PI_LEGACY_MESSAGE_ROLES:
            continue
        if isinstance(message_id, str) and message_id.startswith("admission-user-"):
            continue
        result.append(message)
    return result or None


async def _close_websocket(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except RuntimeError:
        # The peer may have completed the close handshake while another task
        # was reporting its terminal state.
        pass


async def _submit_agent_command(
    websocket: WebSocket,
    runtime: PiRuntimeHandle,
    broker: ChatboxRuntimeBroker,
    chat_session: ChatboxSession,
    provider: ModelProviderRow,
    command: dict[str, Any],
) -> None:
    """Mandatory user-turn ingress; prompt dispatch cannot bypass admission."""

    if command.get("type") != "prompt":
        await runtime.send_command(command)
        return
    message = command.get("message")
    if not isinstance(message, str):
        await broker.record_admission(
            message=None,
            status="ask_for_clarification",
            reason_code="invalid_message",
        )
        return
    admission = AgentAdmissionService(websocket.app)
    decision = await admission.evaluate(
        user_id=chat_session.user_id,
        workspace_id=chat_session.workspace_id,
        session_id=chat_session.id,
        runtime_generation=chat_session.runtime_generation,
        message=message,
        catalog_version=TOOL_CATALOG_VERSION,
        provider=provider,
        recent_messages=list(broker.history.messages),
    )
    if not decision.allowed or decision.receipt is None:
        logger.info(
            "Agent admission rejected session=%s decision=%s reason=%s",
            chat_session.id,
            decision.status,
            decision.reason_code,
        )
        await broker.record_admission(
            message=message,
            status=decision.status,
            reason_code=decision.reason_code,
        )
        return
    if not admission.consume(
        token=decision.receipt,
        session_id=chat_session.id,
        runtime_generation=chat_session.runtime_generation,
        message=message,
        catalog_version=TOOL_CATALOG_VERSION,
    ):
        raise PiRuntimeError("Agent admission receipt is invalid")
    await runtime.send_command(command)


@router.websocket("/{session_id}")
async def chatbox_websocket(websocket: WebSocket, session_id: str) -> None:
    """Stream only new projected Pi events and pass incoming Pi RPC commands unchanged."""

    try:
        context = await _ws_context(websocket)
    except (HTTPException, AppError):
        await websocket.close(code=1008)
        return
    if workspace_rbac_enforced() and context is None:
        return
    workspace_id = (
        context.workspace_id if context is not None else websocket.query_params.get("workspace_id")
    )
    if workspace_id is None:
        await websocket.close(code=1008)
        return
    try:
        chat_session = _get_session(session_id, workspace_id)
        _authorize_session(chat_session, context)
        store: ProviderStore | None = getattr(websocket.app.state, "provider_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="Provider store not initialised")
        provider = _resolve_provider(store, workspace_id, chat_session.provider_id)
    except HTTPException:
        await websocket.close(code=1008)
        return

    try:
        await websocket.accept()
    except (RuntimeError, WebSocketDisconnect):
        return

    restore_started = time.perf_counter()
    await websocket.send_json(
        {
            "type": "runtime_status",
            "status": "restoring",
            "runtime_generation": chat_session.runtime_generation,
        }
    )

    try:
        after_revision = int(websocket.query_params.get("after_revision", "0"))
        if after_revision < 0:
            raise ValueError
    except (TypeError, ValueError):
        await _close_websocket(websocket, 1008)
        return

    try:
        runtime, broker, subscriber = await _claim_chatbox_subscription(
            websocket,
            chat_session,
            provider,
            after_revision,
        )
    except (_ChatboxSessionBusyError, ChatboxBrokerBusyError):
        await _close_websocket(websocket, 1013)
        return
    except ChatboxBrokerResyncError:
        await _close_websocket(websocket, 1012)
        return
    except HTTPException:
        await _close_websocket(websocket, 1008)
        return
    except PiRuntimeError as exc:
        await _stop_session_runtime(
            websocket.app,
            session_id,
            lifecycle_state="dead",
            release_websocket=True,
        )
        logger.warning(
            "Chatbox runtime failed to start session=%s generation=%s "
            "duration_ms=%.1f error_type=%s",
            session_id,
            chat_session.runtime_generation,
            (time.perf_counter() - restore_started) * 1000,
            type(exc).__name__,
        )
        try:
            await websocket.send_json(
                {
                    "type": "runtime_status",
                    "status": "failed",
                    "runtime_generation": chat_session.runtime_generation,
                }
            )
        except (RuntimeError, WebSocketDisconnect):
            pass
        await _close_websocket(websocket, 1011)
        return

    restore_duration_ms = round((time.perf_counter() - restore_started) * 1000, 1)
    logger.info(
        "Chatbox runtime ready session=%s generation=%s duration_ms=%.1f",
        session_id,
        chat_session.runtime_generation,
        restore_duration_ms,
    )
    try:
        await websocket.send_json(
            {
                "type": "runtime_status",
                "status": "ready",
                "runtime_generation": chat_session.runtime_generation,
                "restore_duration_ms": restore_duration_ms,
            }
        )
    except (RuntimeError, WebSocketDisconnect):
        await broker.unsubscribe(subscriber)
        _active_websocket_sessions(websocket.app).discard(session_id)
        return

    sender: asyncio.Task[None] | None = None
    receiver: asyncio.Task[None] | None = None
    runtime_failed = False
    resync_required = False
    try:

        async def send_events() -> None:
            assert subscriber is not None
            while True:
                item = await subscriber.get()
                if isinstance(item, (ChatboxBrokerResyncError, PiRuntimeError)):
                    raise item
                await websocket.send_json(item)

        async def receive_commands() -> None:
            while True:
                command = await websocket.receive_json()
                if isinstance(command, dict):
                    await _submit_agent_command(
                        websocket,
                        runtime,
                        broker,
                        chat_session,
                        provider,
                        command,
                    )

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(receive_commands())
        done, _pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        runtime_failure: BaseException | None = None
        connection_failure: BaseException | None = None
        disconnected = False
        for task in done:
            try:
                task.result()
            except WebSocketDisconnect:
                disconnected = True
            except ChatboxBrokerResyncError:
                resync_required = True
            except PiRuntimeError as exc:
                runtime_failure = exc
            except Exception as exc:
                connection_failure = exc

        if resync_required:
            await _close_websocket(websocket, 1012)
        elif runtime_failure is not None or runtime.state == "dead":
            runtime_failed = True
            logger.warning(
                "Chatbox runtime stream ended session=%s error_type=%s",
                session_id,
                type(runtime_failure).__name__ if runtime_failure is not None else "DeadRuntime",
            )
            await _close_websocket(websocket, 1011)
        elif connection_failure is not None:
            logger.warning(
                "Chatbox websocket task ended session=%s error_type=%s",
                session_id,
                type(connection_failure).__name__,
            )
            await _close_websocket(websocket, 1011)
        elif not disconnected:
            logger.info(
                "Chatbox runtime stream closed session=%s state=%s",
                session_id,
                runtime.state,
            )
            await _close_websocket(websocket, 1000)
    except asyncio.CancelledError:
        # A disappearing WebSocket may cancel the ASGI route itself. This is a
        # connection lifecycle signal, not a runtime failure; the finally
        # block still releases the subscriber and starts the grace TTL.
        logger.debug("Chatbox websocket route cancelled session=%s", session_id)
    finally:
        # ASGI servers may cancel the route task as soon as the peer vanishes.
        # Release the process-local lease synchronously, then shield broker and
        # runtime cleanup so cancellation cannot strand a subscriber or TTL.
        _active_websocket_sessions(websocket.app).discard(session_id)

        async def finish_connection_cleanup() -> None:
            await broker.unsubscribe(subscriber)
            if runtime_failed:
                await _stop_session_runtime(
                    websocket.app,
                    session_id,
                    lifecycle_state="dead",
                    release_websocket=True,
                )

        cleanup_task = asyncio.create_task(finish_connection_cleanup())
        tasks = [task for task in (sender, receiver) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup_task)
