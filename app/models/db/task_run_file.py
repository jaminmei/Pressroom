"""Normalized associations between durable runs and workspace File resources."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRunFile(Base):
    __tablename__ = "task_run_files"
    __table_args__ = (
        Index("idx_task_run_files_file_id", "file_id"),
        Index("idx_task_run_files_workspace_id", "workspace_id"),
    )

    task_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("workspace_files.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
