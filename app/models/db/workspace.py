from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

WorkspaceDeletionCounts = TypedDict(
    "WorkspaceDeletionCounts",
    {
        "members_excluding_owner": int,
        "workflows": int,
        "databases": int,
        "evaluation_runs": int,
        "task_runs": int,
        "workspace_providers": int,
    },
)


class WorkspaceDeletionImpact(TypedDict):
    can_delete: bool
    counts: WorkspaceDeletionCounts


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'deleting')",
            name="ck_workspaces_status",
        ),
        Index("idx_workspaces_slug", "slug", unique=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    # owner_user_id is a denormalized cache; workspace_members is canonical
    # and both are updated atomically with the owner membership row.
    owner_user_id: Mapped[str | None] = mapped_column(
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
