"""Durable, argument-bound approval requests for confirmation tools."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ToolApprovalRequest(Base):
    __tablename__ = "tool_approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired', 'executed')",
            name="status",
        ),
        Index("idx_tool_approval_requests_session_status", "agent_session_id", "status"),
        Index("idx_tool_approval_requests_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    agent_session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chatbox_sessions.id", ondelete="CASCADE"), nullable=False
    )
    runtime_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    argument_digest: Mapped[str] = mapped_column(Text, nullable=False)
    argument_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
