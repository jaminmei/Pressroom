"""Evaluation ground truth ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GroundTruth(Base):
    __tablename__ = "ground_truths"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_ground_truths_document_id_version"),
        Index("idx_ground_truths_document_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    document_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("test_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_task_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
