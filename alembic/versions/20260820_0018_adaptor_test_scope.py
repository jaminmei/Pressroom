"""Persist and scope Adaptor Test Workbench temporary data."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0018"
down_revision: Union[str, Sequence[str], None] = "20260820_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("adaptor_test_cases"):
        op.create_table(
            "adaptor_test_cases",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("workspace_id", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.Text(), nullable=False),
            sa.Column("target_node_id", sa.Text(), nullable=False),
            sa.Column("scope_fingerprint", sa.Text(), nullable=False),
            sa.Column("workflow_fingerprint", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("task_id", sa.Text(), nullable=True),
            sa.Column("workflow_json", sa.JSON(), nullable=False),
            sa.Column("nodes_json", sa.JSON(), nullable=False),
            sa.Column("input_identities_json", sa.JSON(), nullable=False),
            sa.Column("completed_outputs_json", sa.JSON(), nullable=False),
            sa.Column("last_execution_id", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "idx_adaptor_test_cases_workspace_user",
            "adaptor_test_cases",
            ["workspace_id", "created_by_user_id"],
        )
        op.create_index(
            "idx_adaptor_test_cases_expires_at",
            "adaptor_test_cases",
            ["expires_at"],
        )

    if not inspector.has_table("adaptor_test_executions"):
        op.create_table(
            "adaptor_test_executions",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("test_case_id", sa.Text(), nullable=False),
            sa.Column("workspace_id", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=True),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("stdout", sa.Text(), server_default=sa.text("''"), nullable=False),
            sa.Column("stderr", sa.Text(), server_default=sa.text("''"), nullable=False),
            sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("input_mode", sa.Text(), nullable=False),
            sa.Column("bindings_json", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["test_case_id"],
                ["adaptor_test_cases.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "idx_adaptor_test_executions_test_case",
            "adaptor_test_executions",
            ["test_case_id"],
        )
        op.create_index(
            "idx_adaptor_test_executions_workspace_user",
            "adaptor_test_executions",
            ["workspace_id", "created_by_user_id"],
        )
        op.create_index(
            "idx_adaptor_test_executions_expires_at",
            "adaptor_test_executions",
            ["expires_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("adaptor_test_executions"):
        op.drop_table("adaptor_test_executions")
    if inspector.has_table("adaptor_test_cases"):
        op.drop_table("adaptor_test_cases")
