"""Issue and verify short-lived Agent Session credentials without storing raw tokens."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.errors import AppError, ErrorCode
from app.models.auth import AuthenticatedContext
from app.models.db.agent_session_credential import AgentSessionCredential
from app.models.db.chatbox_session import ChatboxSession
from app.models.db.user_account import UserAccount
from app.models.db.workspace_member import WorkspaceMember
from app.services.auth_service import AuthService, SessionFactory

AGENT_SESSION_AUDIENCE = "agent-session"
AGENT_SESSION_TOKEN_PREFIX = "pra_"
AGENT_SESSION_HASH_VERSION = 1
_HASH_DOMAIN = b"docconv/agent-session-token/v1\x00"
_TOKEN_PATTERN = re.compile(r"^pra_([A-Za-z0-9_-]{8})_([A-Za-z0-9_-]{32,})$")


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class IssuedAgentSessionCredential:
    record: AgentSessionCredential
    raw_token: str


class AgentSessionCredentialService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()

    def issue(
        self,
        *,
        agent_session_id: str,
        user_id: str,
        workspace_id: str,
        runtime_generation: int,
    ) -> IssuedAgentSessionCredential:
        now = utcnow_naive()
        secret = secrets.token_urlsafe(32)
        display = secret[:8]
        raw_token = f"{AGENT_SESSION_TOKEN_PREFIX}{display}_{secret}"
        record = AgentSessionCredential(
            id=f"asc_{uuid4()}",
            agent_session_id=agent_session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            runtime_generation=runtime_generation,
            audience=AGENT_SESSION_AUDIENCE,
            prefix=f"{AGENT_SESSION_TOKEN_PREFIX}{display}",
            token_hash=self._hash_token(raw_token),
            hash_version=AGENT_SESSION_HASH_VERSION,
            credential_state="active",
            issued_at=now,
            expires_at=now + timedelta(minutes=self._settings.agent_session_token_ttl_minutes),
        )
        with self._session_factory() as database:
            session = database.get(ChatboxSession, agent_session_id)
            if (
                session is None
                or session.user_id != user_id
                or session.workspace_id != workspace_id
                or session.runtime_generation != runtime_generation
                or session.session_state != "active"
            ):
                raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Agent Session is not active")
            membership = database.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.workspace_id == workspace_id,
                )
            )
            if membership is None:
                raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Workspace membership is unavailable")
            database.execute(
                update(AgentSessionCredential)
                .where(
                    AgentSessionCredential.agent_session_id == agent_session_id,
                    AgentSessionCredential.runtime_generation == runtime_generation,
                    AgentSessionCredential.credential_state == "active",
                )
                .values(credential_state="revoked", revoked_at=now)
            )
            database.add(record)
            database.commit()
            database.refresh(record)
        return IssuedAgentSessionCredential(record=record, raw_token=raw_token)

    def revoke_session(self, agent_session_id: str, *, generation: int | None = None) -> None:
        now = utcnow_naive()
        with self._session_factory() as database:
            statement = update(AgentSessionCredential).where(
                AgentSessionCredential.agent_session_id == agent_session_id,
                AgentSessionCredential.credential_state == "active",
            )
            if generation is not None:
                statement = statement.where(AgentSessionCredential.runtime_generation == generation)
            database.execute(statement.values(credential_state="revoked", revoked_at=now))
            database.commit()

    def revoke_user(self, user_id: str, *, workspace_id: str | None = None) -> None:
        """Revoke active delegated credentials after logout or access changes."""

        now = utcnow_naive()
        with self._session_factory() as database:
            statement = update(AgentSessionCredential).where(
                AgentSessionCredential.user_id == user_id,
                AgentSessionCredential.credential_state == "active",
            )
            if workspace_id is not None:
                statement = statement.where(AgentSessionCredential.workspace_id == workspace_id)
            database.execute(statement.values(credential_state="revoked", revoked_at=now))
            database.commit()

    def require_authenticated(
        self,
        raw_token: str | None,
        *,
        requested_session_id: str | None,
        requested_workspace_id: str | None,
    ) -> AuthenticatedContext:
        if raw_token is None or _TOKEN_PATTERN.fullmatch(raw_token) is None:
            raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Agent Session token is invalid")
        if not requested_session_id or not requested_workspace_id:
            raise AppError(
                ErrorCode.AUTH_TOKEN_INVALID, "Agent Session context headers are required"
            )

        with self._session_factory() as database:
            credential = database.scalar(
                select(AgentSessionCredential).where(
                    AgentSessionCredential.token_hash == self._hash_token(raw_token),
                    AgentSessionCredential.hash_version == AGENT_SESSION_HASH_VERSION,
                    AgentSessionCredential.audience == AGENT_SESSION_AUDIENCE,
                )
            )
            if credential is None or credential.credential_state != "active":
                raise AppError(
                    ErrorCode.AUTH_TOKEN_INVALID, "Agent Session token is invalid or revoked"
                )
            now = utcnow_naive()
            if credential.expires_at <= now:
                credential.credential_state = "expired"
                database.commit()
                raise AppError(ErrorCode.AUTH_TOKEN_EXPIRED, "Agent Session token has expired")
            if (
                credential.agent_session_id != requested_session_id
                or credential.workspace_id != requested_workspace_id
            ):
                raise AppError(
                    ErrorCode.AUTH_TOKEN_INVALID, "Agent Session token scope does not match"
                )
            session = database.get(ChatboxSession, credential.agent_session_id)
            if (
                session is None
                or session.user_id != credential.user_id
                or session.workspace_id != credential.workspace_id
                or session.runtime_generation != credential.runtime_generation
                or session.session_state != "active"
            ):
                raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Agent Session token is stale")
            membership = database.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.user_id == credential.user_id,
                    WorkspaceMember.workspace_id == credential.workspace_id,
                )
            )
            if membership is None:
                raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Workspace membership is unavailable")
            user = database.get(UserAccount, credential.user_id)
            if user is None:
                raise AppError(ErrorCode.AUTH_TOKEN_INVALID, "Agent Session owner is unavailable")
            credential.last_used_at = now
            database.commit()
            return AuthService(
                session_factory=self._session_factory,
                settings=self._settings,
            ).build_context_for_credential(
                session=database,
                user=user,
                credential_id=credential.id,
                expires_at=credential.expires_at,
                auth_kind="agent_session_token",
                workspace_id=credential.workspace_id,
            )

    def _hash_token(self, raw_token: str) -> str:
        secret = self._settings.auth_session_secret
        if not secret:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "AUTH_SESSION_SECRET is required for Agent Session credentials",
            )
        return hmac.new(
            secret.encode("utf-8"),
            _HASH_DOMAIN + raw_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
