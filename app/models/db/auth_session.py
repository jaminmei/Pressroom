"""Server-side auth session ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("idx_auth_sessions_token_hash", "session_token_hash", unique=True),
        Index("idx_auth_sessions_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False)
    session_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
