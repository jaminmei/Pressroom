"""Create durable storage cleanup outbox."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0021"
down_revision: Union[str, Sequence[str], None] = "20260820_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("storage_cleanup_jobs"):
        return
    op.create_table(
        "storage_cleanup_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_storage_cleanup_jobs_status",
        "storage_cleanup_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_storage_cleanup_jobs_workspace",
        "storage_cleanup_jobs",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("storage_cleanup_jobs"):
        op.drop_table("storage_cleanup_jobs")
