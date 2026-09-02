"""Short-lived delegated credentials for managed Agent Session tool calls."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentSessionCredential(Base):
    __tablename__ = "agent_session_credentials"
    __table_args__ = (
        CheckConstraint(
            "credential_state IN ('active', 'expired', 'revoked')",
            name="credential_state",
        ),
        Index("idx_agent_session_credentials_token_hash", "token_hash", unique=True),
        Index(
            "idx_agent_session_credentials_session_generation",
            "agent_session_id",
            "runtime_generation",
        ),
        Index("idx_agent_session_credentials_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    agent_session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chatbox_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    runtime_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    audience: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'agent-session'")
    )
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hash_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    credential_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
