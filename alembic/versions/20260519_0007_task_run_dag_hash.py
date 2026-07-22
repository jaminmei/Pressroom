"""Add dag_hash and input_files_json columns to task_runs

Revision ID: 20260519_0007
Revises: 20260518_0006
"""

import sqlalchemy as sa

from alembic import op

revision = "20260519_0007"
down_revision = "20260518_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_runs",
        sa.Column("dag_hash", sa.Text, nullable=True),
    )
    op.add_column(
        "task_runs",
        sa.Column("input_files_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_runs", "input_files_json")
    op.drop_column("task_runs", "dag_hash")
