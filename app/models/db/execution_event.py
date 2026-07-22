"""Execution event ORM model — append-only log for workflow node execution."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        Index("idx_exec_events_run_seq", "workflow_run_id", "sequence"),
        Index("idx_exec_events_run_node", "workflow_run_id", "node_id"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resolved_inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
