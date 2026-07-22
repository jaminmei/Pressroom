"""Immutable workflow version snapshot ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowVersionRecord(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_id_version"),
        Index("idx_workflow_versions_workflow_id", "workflow_id"),
        Index("idx_workflow_versions_workflow_dag_hash", "workflow_id", "dag_hash"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(Text, ForeignKey("workflows.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="saved")
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dag_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
