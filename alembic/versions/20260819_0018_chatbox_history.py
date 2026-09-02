"""Add authoritative reconnect snapshots to chatbox sessions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_0018"
down_revision: Union[str, Sequence[str], None] = "20260814_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbox_sessions",
        sa.Column("messages_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "chatbox_sessions",
        sa.Column(
            "tool_executions_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
        ),
    )
    op.add_column(
        "chatbox_sessions",
        sa.Column(
            "compaction_notes_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )
    op.add_column("chatbox_sessions", sa.Column("live_message_id", sa.Text(), nullable=True))
    op.add_column(
        "chatbox_sessions",
        sa.Column("snapshot_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("chatbox_sessions", "snapshot_revision")
    op.drop_column("chatbox_sessions", "live_message_id")
    op.drop_column("chatbox_sessions", "compaction_notes_json")
    op.drop_column("chatbox_sessions", "tool_executions_json")
    op.drop_column("chatbox_sessions", "messages_json")
