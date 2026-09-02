"""Add durable chatbox session ownership records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_0017"
down_revision: Union[str, Sequence[str], None] = "20260717_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chatbox_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("pi_session_ref", sa.Text(), nullable=True),
        sa.Column(
            "lifecycle_state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'idle'"),
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("lifecycle_state IN ('active', 'idle', 'dead')", name="lifecycle_state"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_chatbox_sessions_workspace_id", "chatbox_sessions", ["workspace_id"])
    op.create_index("idx_chatbox_sessions_user_id", "chatbox_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_chatbox_sessions_user_id", table_name="chatbox_sessions")
    op.drop_index("idx_chatbox_sessions_workspace_id", table_name="chatbox_sessions")
    op.drop_table("chatbox_sessions")
