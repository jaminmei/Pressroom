"""Add dag_hash column to workflow_versions for same-workflow dedup

Revision ID: 20260520_0009
Revises: 20260519_0008
"""

import sqlalchemy as sa

from alembic import op

revision = "20260520_0009"
down_revision = "20260519_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_versions",
        sa.Column("dag_hash", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_workflow_versions_workflow_dag_hash",
        "workflow_versions",
        ["workflow_id", "dag_hash"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_versions_workflow_dag_hash", "workflow_versions")
    op.drop_column("workflow_versions", "dag_hash")
