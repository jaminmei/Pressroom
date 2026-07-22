"""Create task_event_logs table for SSE replay."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260304_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_task_runs_for_fk() -> None:
    """Bootstrap a minimal task_runs table when FK target does not exist yet."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("task_runs"):
        return

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_task_runs"),
        comment="Bootstrap table for task_event_logs FK target.",
    )


def upgrade() -> None:
    _ensure_task_runs_for_fk()
    op.create_table(
        "task_event_logs",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_run_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_run_id"],
            ["task_runs.id"],
            name="fk_task_event_logs_task_run_id_task_runs",
        ),
        sa.PrimaryKeyConstraint("seq", name="pk_task_event_logs"),
    )
    op.create_index(
        "idx_event_logs_task_seq",
        "task_event_logs",
        ["task_run_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_event_logs_task_seq", table_name="task_event_logs")
    op.drop_table("task_event_logs")
    # Keep task_runs in downgrade path to avoid accidental data loss when this table
    # already existed before 20260304_0001 and happened to share the same minimal schema.
