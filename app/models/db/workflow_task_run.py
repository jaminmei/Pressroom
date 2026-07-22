"""Idempotency record tying a published workflow to a task run."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowTaskRun(Base):
    __tablename__ = "workflow_task_runs"
    __table_args__ = (
        Index("ix_workflow_task_runs_workflow_hash", "workflow_hash"),
        UniqueConstraint("workflow_hash", "task_run_id", name="uq_workflow_task_run"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workflow_hash: Mapped[str] = mapped_column(Text, nullable=False)
    dag_hash: Mapped[str] = mapped_column(Text, nullable=False)
    task_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
