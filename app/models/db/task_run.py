"""TaskRun ORM model for durable task snapshot persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (Index("idx_task_runs_workspace_id", "workspace_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    evaluation_run_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("evaluation_runs.id"),
        nullable=True,
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dag_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_files_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
