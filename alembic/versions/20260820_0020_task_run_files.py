"""Normalize durable run references to workspace files."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0020"
down_revision: Union[str, Sequence[str], None] = "20260820_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("task_run_files"):
        return
    op.create_table(
        "task_run_files",
        sa.Column("task_run_id", sa.Text(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["workspace_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_run_id", "file_id"),
    )
    op.create_index("idx_task_run_files_file_id", "task_run_files", ["file_id"])
    op.create_index(
        "idx_task_run_files_workspace_id",
        "task_run_files",
        ["workspace_id"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("task_run_files"):
        op.drop_table("task_run_files")
