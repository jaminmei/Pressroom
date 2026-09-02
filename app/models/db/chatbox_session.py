"""Durable ownership and lifecycle record for one Pi chatbox session."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatboxSession(Base):
    """Mutable ORM record because runtime lifecycle is updated by the WS boundary."""

    __tablename__ = "chatbox_sessions"
    __table_args__ = (
        CheckConstraint("lifecycle_state IN ('active', 'idle', 'dead')", name="lifecycle_state"),
        CheckConstraint(
            "session_state IN ('draft', 'active', 'paused', 'archived')",
            name="session_state",
        ),
        CheckConstraint(
            "runtime_state IN ('stopped', 'starting', 'idle', 'running', 'failed')",
            name="runtime_state",
        ),
        Index("idx_chatbox_sessions_workspace_id", "workspace_id"),
        Index("idx_chatbox_sessions_user_id", "user_id"),
        Index(
            "idx_chatbox_sessions_user_workspace_activity",
            "user_id",
            "workspace_id",
            "last_activity_at",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    pi_session_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="idle", server_default=text("'idle'")
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft", server_default=text("'draft'")
    )
    runtime_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="stopped", server_default=text("'stopped'")
    )
    runtime_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    checkpoint_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    checkpoint_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    checkpoint_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    messages_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    tool_executions_json: Mapped[dict[str, dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    compaction_notes_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    live_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    first_settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
