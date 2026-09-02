"""Server-owned current Agent Session pointer for one user/workspace pair."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatboxSessionSelection(Base):
    __tablename__ = "chatbox_session_selections"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="user_workspace"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("chatbox_sessions.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
