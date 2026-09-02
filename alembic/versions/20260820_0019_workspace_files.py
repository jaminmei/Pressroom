"""Create durable workspace file resources."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0019"
down_revision: Union[str, Sequence[str], None] = "20260820_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("workspace_files"):
        return
    op.create_table(
        "workspace_files",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cleanup_error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "idx_workspace_files_workspace_status",
        "workspace_files",
        ["workspace_id", "status"],
    )
    op.create_index(
        "idx_workspace_files_uploaded_by",
        "workspace_files",
        ["uploaded_by_user_id"],
    )
    op.create_index(
        "idx_workspace_files_created_at",
        "workspace_files",
        ["created_at"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("workspace_files"):
        op.drop_table("workspace_files")
