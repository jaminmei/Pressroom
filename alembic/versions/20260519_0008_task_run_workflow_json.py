"""Add workflow_json column to task_runs for workflow restoration

Revision ID: 20260519_0008
Revises: 20260519_0007
"""

import sqlalchemy as sa

from alembic import op

revision = "20260519_0008"
down_revision = "20260519_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_runs",
        sa.Column("workflow_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_runs", "workflow_json")
