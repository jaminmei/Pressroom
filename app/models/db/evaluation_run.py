"""Evaluation batch run ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("idx_evaluation_runs_test_set_id", "test_set_id"),
        Index("idx_evaluation_runs_workflow_id", "workflow_id"),
        Index("idx_evaluation_runs_workspace_id", "workspace_id"),
        Index(
            "uq_evaluation_runs_active_test_set",
            "test_set_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
        Index(
            "uq_evaluation_runs_client_request",
            "test_set_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
            sqlite_where=text("client_request_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_set_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("test_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    total_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
