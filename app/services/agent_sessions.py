"""Durable multi-session selection and navigation metadata."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.db.chatbox_session import ChatboxSession
from app.models.db.chatbox_session_selection import ChatboxSessionSelection

_WHITESPACE = re.compile(r"\s+")
_TITLE_LIMIT = 72
_PREVIEW_LIMIT = 180


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class SessionActivation:
    session: ChatboxSession
    previous_session_id: str | None
    changed: bool


class AgentSessionService:
    def list_for_user_workspace(
        self,
        *,
        user_id: str,
        workspace_id: str,
        view: Literal["conversations", "archived", "all"] = "conversations",
    ) -> list[ChatboxSession]:
        with SessionLocal() as database:
            statement = select(ChatboxSession).where(
                ChatboxSession.user_id == user_id,
                ChatboxSession.workspace_id == workspace_id,
            )
            if view == "conversations":
                statement = statement.where(ChatboxSession.session_state != "archived")
            elif view == "archived":
                statement = statement.where(ChatboxSession.session_state == "archived")
            sessions = list(
                database.scalars(
                    statement.order_by(
                        ChatboxSession.last_activity_at.desc(),
                        ChatboxSession.created_at.desc(),
                        ChatboxSession.id.desc(),
                    )
                )
            )
            metadata_changed = False
            for session in sessions:
                metadata_changed = _backfill_navigation_metadata(session) or metadata_changed
            if metadata_changed:
                database.commit()
            return sessions

    def current(self, *, user_id: str, workspace_id: str) -> ChatboxSession | None:
        with SessionLocal() as database:
            selection = self._selection(database, user_id=user_id, workspace_id=workspace_id)
            if selection is None or selection.session_id is None:
                return None
            session = database.get(ChatboxSession, selection.session_id)
            if (
                session is None
                or session.user_id != user_id
                or session.workspace_id != workspace_id
                or session.session_state == "archived"
            ):
                return None
            assert isinstance(session, ChatboxSession)
            if _backfill_navigation_metadata(session):
                database.commit()
            return session

    def create_draft(
        self,
        *,
        user_id: str,
        workspace_id: str,
        provider_id: str,
    ) -> ChatboxSession:
        now = utcnow_naive()
        session = ChatboxSession(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_id=user_id,
            provider_id=provider_id,
            lifecycle_state="idle",
            session_state="draft",
            runtime_state="stopped",
            runtime_generation=0,
            last_activity_at=now,
            created_at=now,
            updated_at=now,
        )
        with SessionLocal() as database:
            database.add(session)
            database.commit()
            database.refresh(session)
            return session

    def activate(
        self,
        *,
        session_id: str,
        user_id: str,
        workspace_id: str,
    ) -> SessionActivation:
        now = utcnow_naive()
        with SessionLocal() as database:
            target = self._owned_session(
                database,
                session_id=session_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            if target.session_state == "archived":
                raise LookupError("Agent Session is archived")
            selection = self._selection(database, user_id=user_id, workspace_id=workspace_id)
            previous_id = selection.session_id if selection is not None else None
            changed = previous_id != target.id or target.session_state != "active"
            if previous_id and previous_id != target.id:
                previous = database.get(ChatboxSession, previous_id)
                if previous is not None and previous.session_state != "archived":
                    previous.session_state = "paused"
                    previous.runtime_state = "stopped"
                    previous.lifecycle_state = "idle"
                    previous.pi_session_ref = None
                    previous.updated_at = now
            if selection is None:
                selection = ChatboxSessionSelection(
                    id=f"css_{uuid.uuid4()}",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    session_id=target.id,
                    updated_at=now,
                )
                database.add(selection)
            else:
                selection.session_id = target.id
                selection.updated_at = now
            if changed:
                target.runtime_generation += 1
            target.session_state = "active"
            target.runtime_state = "stopped"
            target.lifecycle_state = "idle"
            target.pi_session_ref = None
            target.archived_at = None
            target.last_activity_at = now
            target.updated_at = now
            _backfill_navigation_metadata(target)
            database.commit()
            database.refresh(target)
            return SessionActivation(target, previous_id, changed)

    def pause(self, *, session_id: str, user_id: str, workspace_id: str) -> ChatboxSession:
        """Pause a Session and clear it as the workspace's current selection."""

        return self._pause(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            clear_selection=True,
        )

    def suspend(self, *, session_id: str, user_id: str, workspace_id: str) -> ChatboxSession:
        """Pause a Session while retaining it as the workspace's resume target."""

        return self._pause(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            clear_selection=False,
        )

    def _pause(
        self,
        *,
        session_id: str,
        user_id: str,
        workspace_id: str,
        clear_selection: bool,
    ) -> ChatboxSession:
        now = utcnow_naive()
        with SessionLocal() as database:
            session = self._owned_session(
                database,
                session_id=session_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            if session.session_state != "archived":
                session.session_state = "paused"
                session.runtime_state = "stopped"
                session.lifecycle_state = "idle"
                session.pi_session_ref = None
                session.updated_at = now
            selection = self._selection(database, user_id=user_id, workspace_id=workspace_id)
            if clear_selection and selection is not None and selection.session_id == session_id:
                selection.session_id = None
                selection.updated_at = now
            database.commit()
            database.refresh(session)
            return session

    def archive(self, *, session_id: str, user_id: str, workspace_id: str) -> ChatboxSession:
        session = self.pause(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        now = utcnow_naive()
        with SessionLocal() as database:
            persistent = self._owned_session(
                database,
                session_id=session.id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            persistent.session_state = "archived"
            persistent.archived_at = now
            persistent.updated_at = now
            database.commit()
            database.refresh(persistent)
            return persistent

    def unarchive(
        self,
        *,
        session_id: str,
        user_id: str,
        workspace_id: str,
    ) -> ChatboxSession:
        """Return an archived Session to the paused conversation list."""

        now = utcnow_naive()
        with SessionLocal() as database:
            session = self._owned_session(
                database,
                session_id=session_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            if session.session_state != "archived":
                raise RuntimeError("Agent Session is not archived")
            session.session_state = "paused"
            session.runtime_state = "stopped"
            session.lifecycle_state = "idle"
            session.pi_session_ref = None
            session.archived_at = None
            session.updated_at = now
            database.commit()
            database.refresh(session)
            return session

    def delete_archived(
        self,
        *,
        session_id: str,
        user_id: str,
        workspace_id: str,
    ) -> str | None:
        """Permanently delete one archived Session and return its checkpoint ref."""

        with SessionLocal() as database:
            session = self._owned_session(
                database,
                session_id=session_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            if session.session_state != "archived":
                raise RuntimeError("Only archived Agent Sessions can be deleted")
            checkpoint_ref = session.checkpoint_ref
            database.delete(session)
            database.commit()
            return checkpoint_ref

    @staticmethod
    def _selection(
        database: Session,
        *,
        user_id: str,
        workspace_id: str,
    ) -> ChatboxSessionSelection | None:
        return database.scalar(
            select(ChatboxSessionSelection).where(
                ChatboxSessionSelection.user_id == user_id,
                ChatboxSessionSelection.workspace_id == workspace_id,
            )
        )

    @staticmethod
    def _owned_session(
        database: Session,
        *,
        session_id: str,
        user_id: str,
        workspace_id: str,
    ) -> ChatboxSession:
        session = database.get(ChatboxSession, session_id)
        if session is None or session.user_id != user_id or session.workspace_id != workspace_id:
            raise LookupError("Agent Session not found")
        return session


def derive_navigation_metadata(messages: list[dict[str, object]]) -> tuple[str, str]:
    """Build a stable, non-blocking fallback title and preview from settled history."""

    texts: list[str] = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        text = " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        normalized = _WHITESPACE.sub(" ", text).strip()
        if normalized:
            texts.append(normalized)
        if len(texts) >= 2:
            break
    seed = texts[0] if texts else "New conversation"
    title = seed if len(seed) <= _TITLE_LIMIT else f"{seed[: _TITLE_LIMIT - 1].rstrip()}…"
    preview_source = " — ".join(texts) if texts else seed
    preview = (
        preview_source
        if len(preview_source) <= _PREVIEW_LIMIT
        else f"{preview_source[: _PREVIEW_LIMIT - 1].rstrip()}…"
    )
    return title, preview


def _backfill_navigation_metadata(session: ChatboxSession) -> bool:
    """Fill navigation labels for conversations created before Admission persisted them.

    Empty drafts deliberately remain untitled so the UI can keep treating them
    as disposable ``New conversation`` placeholders. This compatibility path
    changes no activity or settled timestamp.
    """

    if not session.messages_json or (session.title is not None and session.preview is not None):
        return False
    title, preview = derive_navigation_metadata(session.messages_json)
    session.title = session.title or title
    session.preview = session.preview or preview
    return True
