from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.errors import AppError, ErrorCode
from app.models.auth import AuthenticatedContext, AuthSessionInfo, AuthUser
from app.models.db.auth_session import AuthSession
from app.models.db.user_account import UserAccount
from app.models.db.workspace_member import WorkspaceMember
from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole
from app.services.workspace_rbac import workspace_rbac_enforced
from app.services.workspace_resolver import resolve_default_workspace

SessionFactory = Callable[[], Session]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_ITERATIONS = 390000


@dataclass
class IssuedAuthContext:
    context: AuthenticatedContext
    raw_session_token: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_naive() -> datetime:
    return _utcnow().replace(tzinfo=None)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


class AuthService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()

    def register(self, *, email: str, password: str, name: str | None = None) -> IssuedAuthContext:
        normalized_email = self._normalize_email(email)
        normalized_name = name.strip() if isinstance(name, str) and name.strip() else None
        self._validate_password(password)

        with self._session_factory() as session:
            existing = self._get_user_by_email(session, normalized_email)
            if existing is not None:
                raise AppError(
                    ErrorCode.AUTH_EMAIL_ALREADY_EXISTS,
                    "此 email 已被註冊",
                    details={"email": normalized_email},
                )

            now = _utcnow_naive()
            user = UserAccount(
                id=f"usr_{uuid4()}",
                email=normalized_email,
                password_hash=self._hash_password(password),
                name=normalized_name,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()

            issued = self._issue_session(session, user=user, now=now)
            session.commit()
            return issued

    def login(self, *, email: str, password: str) -> IssuedAuthContext:
        normalized_email = self._normalize_email(email)

        with self._session_factory() as session:
            user = self._get_user_by_email(session, normalized_email)
            if user is None or not self._verify_password(password, user.password_hash):
                raise AppError(
                    ErrorCode.AUTH_INVALID_CREDENTIALS,
                    "帳號或密碼不正確",
                    details={"email": normalized_email},
                )

            issued = self._issue_session(session, user=user, now=_utcnow_naive())
            session.commit()
            return issued

    def logout(self, raw_session_token: str | None) -> None:
        if not raw_session_token:
            return

        with self._session_factory() as session:
            auth_session = self._find_session(session, raw_session_token)
            if auth_session is None:
                return
            auth_session.revoked_at = _utcnow_naive()
            session.add(auth_session)
            session.commit()

    def require_authenticated(self, raw_session_token: str | None) -> AuthenticatedContext:
        if not raw_session_token:
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "此操作需要登入",
                details={"cookie_name": self._settings.auth_session_cookie_name},
            )

        with self._session_factory() as session:
            auth_session = self._find_session(session, raw_session_token)
            if auth_session is None:
                raise AppError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "登入 session 已過期，請重新登入",
                    details={"reason": "missing"},
                )

            now = _utcnow_naive()
            if auth_session.revoked_at is not None:
                raise AppError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "登入 session 已失效，請重新登入",
                    details={"reason": "revoked"},
                )
            if auth_session.expires_at <= now:
                auth_session.revoked_at = now
                session.add(auth_session)
                session.commit()
                raise AppError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "登入 session 已過期，請重新登入",
                    details={"reason": "expired"},
                )

            user = session.get(UserAccount, auth_session.user_id)
            if user is None:
                raise AppError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "找不到對應使用者，請重新登入",
                    details={"reason": "user_missing"},
                )

            auth_session.last_seen_at = now
            session.add(auth_session)
            session.commit()
            return self._build_context(session=session, user=user, auth_session=auth_session)

    def _issue_session(
        self, session: Session, *, user: UserAccount, now: datetime
    ) -> IssuedAuthContext:
        raw_session_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=self._settings.auth_session_ttl_hours)
        auth_session = AuthSession(
            id=f"as_{uuid4()}",
            user_id=user.id,
            session_token_hash=self._hash_session_token(raw_session_token),
            expires_at=expires_at,
            created_at=now,
            last_seen_at=now,
        )
        session.add(auth_session)
        session.flush()
        return IssuedAuthContext(
            context=self._build_context(session=session, user=user, auth_session=auth_session),
            raw_session_token=raw_session_token,
        )

    def _build_context(
        self,
        *,
        session: Session,
        user: UserAccount,
        auth_session: AuthSession,
    ) -> AuthenticatedContext:
        return self.build_context_for_credential(
            session=session,
            user=user,
            credential_id=auth_session.id,
            expires_at=auth_session.expires_at,
            auth_kind="session",
        )

    def build_context_for_credential(
        self,
        *,
        session: Session,
        user: UserAccount,
        credential_id: str,
        expires_at: datetime,
        auth_kind: Literal["session", "agent_session_token"],
        workspace_id: str | None = None,
    ) -> AuthenticatedContext:
        """Build the shared user/workspace context for an authenticated credential."""
        resolved_workspace_id: str | None = workspace_id
        role: WorkspaceRole | None = None
        capabilities: frozenset[str] = frozenset()

        if workspace_rbac_enforced(self._settings):
            resolved_workspace_id = workspace_id or resolve_default_workspace(session, user.id)
            membership = session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == resolved_workspace_id,
                )
            ).scalar_one()
            role = WorkspaceRole(membership.role)
            capabilities = CAPABILITIES[role]

        return AuthenticatedContext(
            user=AuthUser(
                id=user.id,
                email=user.email,
                name=user.name,
                created_at=_as_aware(user.created_at),
            ),
            session=AuthSessionInfo(
                id=credential_id,
                user_id=user.id,
                expires_at=_as_aware(expires_at),
            ),
            workspace_id=resolved_workspace_id,
            role=role,
            capabilities=capabilities,
            auth_kind=auth_kind,
        )

    def _find_session(self, session: Session, raw_session_token: str) -> AuthSession | None:
        statement: Select[tuple[AuthSession]] = select(AuthSession).where(
            AuthSession.session_token_hash == self._hash_session_token(raw_session_token)
        )
        return session.execute(statement).scalar_one_or_none()

    def _get_user_by_email(self, session: Session, email: str) -> UserAccount | None:
        statement: Select[tuple[UserAccount]] = select(UserAccount).where(
            UserAccount.email == email
        )
        return session.execute(statement).scalar_one_or_none()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _PASSWORD_ITERATIONS,
        )
        return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        algorithm, raw_iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(raw_iterations),
        )
        return hmac.compare_digest(derived.hex(), digest_hex)

    def _hash_session_token(self, raw_session_token: str) -> str:
        secret = self._settings.auth_session_secret
        if not secret:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "AUTH_SESSION_SECRET 未設定，無法建立或驗證登入 session",
            )
        return hmac.new(
            secret.encode("utf-8"),
            raw_session_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _normalize_email(self, email: str) -> str:
        normalized = email.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise AppError(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                "Email 格式不正確",
                details={"email": normalized},
            )
        return normalized

    def _validate_password(self, password: str) -> None:
        if len(password) < 8:
            raise AppError(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                "密碼長度至少需要 8 個字元",
            )
