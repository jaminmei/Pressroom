"""Durable Celery publication state for evaluation results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DISPATCH_PENDING = "pending"
DISPATCH_PUBLISHING = "publishing"
DISPATCH_PUBLISHED = "published"
DISPATCH_CANCELLED = "cancelled"
DISPATCH_STATUSES = frozenset(
    {
        DISPATCH_PENDING,
        DISPATCH_PUBLISHING,
        DISPATCH_PUBLISHED,
        DISPATCH_CANCELLED,
    }
)


class EvaluationDispatchOutbox(Base):
    """One durable publication record for each queued evaluation result."""

    __tablename__ = "evaluation_dispatch_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'cancelled')",
            name="ck_evaluation_dispatch_outbox_status",
        ),
        Index(
            "idx_evaluation_dispatch_outbox_available",
            "status",
            "available_at",
        ),
        Index(
            "idx_evaluation_dispatch_outbox_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    evaluation_result_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("evaluation_results.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    task_run_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DISPATCH_PENDING,
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
