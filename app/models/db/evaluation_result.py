"""Evaluation result ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        Index("idx_evaluation_results_run_id", "evaluation_run_id"),
        Index("idx_evaluation_results_document_id", "document_id"),
        Index("uq_evaluation_results_task_run_id", "task_run_id", unique=True),
        Index(
            "uq_evaluation_results_run_document",
            "evaluation_run_id",
            "document_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    evaluation_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("test_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_run_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("task_runs.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str | None] = mapped_column(
        Text, nullable=True, server_default=text("'unreviewed'")
    )
    accepted_ground_truth_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison_status: Mapped[str | None] = mapped_column(
        Text, nullable=True, server_default=text("'not_compared'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
