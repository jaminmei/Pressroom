"""Workspace integrity constraints and query indexes.

Revision ID: 20260714_0013
Revises: 20260708_0012
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_0013"
down_revision: Union[str, Sequence[str], None] = "20260708_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESOURCE_TIME_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("idx_workflows_workspace_id_created_at", "workflows", "created_at"),
    ("idx_test_sets_workspace_id_created_at", "test_sets", "created_at"),
    ("idx_evaluation_runs_workspace_id_created_at", "evaluation_runs", "created_at"),
    ("idx_task_runs_workspace_id_created_at", "task_runs", "created_at"),
)


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.create_check_constraint(
            "ck_workspaces_status",
            "status IN ('active', 'deleting')",
        )

    owner_filter = sa.text("role = 'owner'")
    op.create_index(
        "uq_workspace_members_owner_workspace_id",
        "workspace_members",
        ["workspace_id"],
        unique=True,
        postgresql_where=owner_filter,
        sqlite_where=owner_filter,
    )
    for index_name, table_name, time_column in RESOURCE_TIME_INDEXES:
        op.create_index(index_name, table_name, ["workspace_id", time_column])


def downgrade() -> None:
    for index_name, table_name, _time_column in reversed(RESOURCE_TIME_INDEXES):
        op.drop_index(index_name, table_name=table_name)
    op.drop_index(
        "uq_workspace_members_owner_workspace_id",
        table_name="workspace_members",
    )
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("ck_workspaces_status", type_="check")
    op.drop_column("workspaces", "status")
