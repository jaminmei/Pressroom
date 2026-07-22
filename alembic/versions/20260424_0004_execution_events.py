"""Create execution_events table for append-only workflow node event logging."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424_0004"
down_revision: Union[str, Sequence[str], None] = "20260319_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("resolved_inputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_execution_events"),
    )
    op.create_index("idx_exec_events_run_seq", "execution_events", ["workflow_run_id", "sequence"])
    op.create_index("idx_exec_events_run_node", "execution_events", ["workflow_run_id", "node_id"])


def downgrade() -> None:
    op.drop_index("idx_exec_events_run_node", table_name="execution_events")
    op.drop_index("idx_exec_events_run_seq", table_name="execution_events")
    op.drop_table("execution_events")
