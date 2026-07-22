"""Persist workspace ownership for API keys and usage records.

Revision ID: 20260715_0014
Revises: 20260714_0013
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260715_0014"
down_revision: Union[str, Sequence[str], None] = "20260714_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("api_keys", "api_invocations"):
        op.add_column(table_name, sa.Column("workspace_id", sa.Text(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET workspace_id = ("
                "SELECT workspace_id FROM workflows WHERE workflows.id = "
                f"{table_name}.workflow_id) WHERE workspace_id IS NULL"
            )
        )
        op.create_index(f"idx_{table_name}_workspace_id", table_name, ["workspace_id"])


def downgrade() -> None:
    for table_name in ("api_invocations", "api_keys"):
        op.drop_index(f"idx_{table_name}_workspace_id", table_name=table_name)
        op.drop_column(table_name, "workspace_id")
