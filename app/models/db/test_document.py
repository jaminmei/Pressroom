"""Evaluation test document ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TestDocument(Base):
    __tablename__ = "test_documents"
    __table_args__ = (
        Index("idx_test_documents_storage_path", "storage_path", unique=True),
        Index("idx_test_documents_test_set_id", "test_set_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    test_set_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("test_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
