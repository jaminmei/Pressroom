"""Cascade workflow deletion to API keys and invocation history.

Revision ID: 20260716_0015
Revises: 20260715_0014
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_0015"
down_revision: Union[str, Sequence[str], None] = "20260715_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINTS: tuple[tuple[str, str], ...] = (
    ("api_keys", "fk_api_keys_workflow_id_workflows"),
    ("api_invocations", "fk_api_invocations_workflow_id_workflows"),
)


def upgrade() -> None:
    # Historical rows predate workflow foreign keys. Remove only records whose
    # owning workflow no longer exists before adding the constraints.
    for table_name in ("api_invocations", "api_keys"):
        op.execute(
            sa.text(
                f"DELETE FROM {table_name} WHERE NOT EXISTS ("
                "SELECT 1 FROM workflows WHERE workflows.id = "
                f"{table_name}.workflow_id)"
            )
        )

    for table_name, constraint_name in _CONSTRAINTS:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_foreign_key(
                constraint_name,
                "workflows",
                ["workflow_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    # Downgrade removes the constraints only. Cleaned orphan rows cannot and
    # should not be reconstructed.
    for table_name, constraint_name in reversed(_CONSTRAINTS):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
