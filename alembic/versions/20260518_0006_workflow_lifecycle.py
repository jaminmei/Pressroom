"""Add published_workflows and workflow_task_runs tables

Revision ID: 20260518_0006
Revises: 20260513_0005
"""

import sqlalchemy as sa

from alembic import op

revision = "20260518_0006"
down_revision = "20260513_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "published_workflows",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("dag_hash", sa.Text, nullable=False),
        sa.Column("definition_json", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("dag_hash", name="uq_published_workflows_dag_hash"),
    )

    op.create_table(
        "workflow_task_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workflow_hash", sa.Text, nullable=False),
        sa.Column("dag_hash", sa.Text, nullable=False),
        sa.Column("task_run_id", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Index("ix_workflow_task_runs_workflow_hash", "workflow_hash"),
        sa.UniqueConstraint("workflow_hash", "task_run_id", name="uq_workflow_task_run"),
    )


def downgrade() -> None:
    op.drop_table("workflow_task_runs")
    op.drop_table("published_workflows")
