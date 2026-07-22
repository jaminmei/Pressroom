"""API Forward invocation ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiInvocation(Base):
    __tablename__ = "api_invocations"
    __table_args__ = (
        Index("idx_api_invocations_workflow_created", "workflow_id", "created_at"),
        Index("idx_api_invocations_run_id", "workflow_run_id"),
        Index("idx_api_invocations_key_id", "api_key_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint_kind: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_status: Mapped[str] = mapped_column(Text, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
