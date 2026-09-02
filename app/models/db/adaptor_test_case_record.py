"""Durable, workspace-scoped Adaptor Test Workbench records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdaptorTestCaseRecord(Base):
    __tablename__ = "adaptor_test_cases"
    __table_args__ = (
        Index("idx_adaptor_test_cases_workspace_user", "workspace_id", "created_by_user_id"),
        Index("idx_adaptor_test_cases_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    nodes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_identities_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    completed_outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    last_execution_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class AdaptorTestExecutionRecord(Base):
    __tablename__ = "adaptor_test_executions"
    __table_args__ = (
        Index("idx_adaptor_test_executions_test_case", "test_case_id"),
        Index(
            "idx_adaptor_test_executions_workspace_user",
            "workspace_id",
            "created_by_user_id",
        ),
        Index("idx_adaptor_test_executions_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    test_case_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("adaptor_test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    stderr: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    input_mode: Mapped[str] = mapped_column(Text, nullable=False)
    bindings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
