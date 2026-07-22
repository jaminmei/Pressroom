"""Durable shared workflow head record."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowRecord(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        Index("idx_workflows_workflow_key", "workflow_key", unique=True),
        Index("idx_workflows_updated_at", "updated_at"),
        Index("idx_workflows_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workflow_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    current_definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("users.id"),
        nullable=True,
    )
    last_saved_by_user_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("users.id"),
        nullable=True,
    )
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
