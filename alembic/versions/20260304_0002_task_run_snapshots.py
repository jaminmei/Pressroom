"""Extend task_runs for history/result snapshot persistence."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260304_0002"
down_revision: Union[str, Sequence[str], None] = "20260304_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_task_runs_table() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("task_runs"):
        return

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_task_runs"),
    )


def _get_task_run_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("task_runs"):
        return set()
    return {str(column["name"]) for column in inspector.get_columns("task_runs")}


def _add_column_if_missing(column: sa.Column[object]) -> None:
    existing = _get_task_run_columns()
    if column.name in existing:
        return
    op.add_column("task_runs", column)


def upgrade() -> None:
    _ensure_task_runs_table()

    _add_column_if_missing(sa.Column("status", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("workflow_id", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("workflow_name", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(sa.Column("completed_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(sa.Column("duration_ms", sa.Integer(), nullable=True))
    _add_column_if_missing(sa.Column("node_summary_json", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("result_preview", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("results_json", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("error", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    columns = _get_task_run_columns()
    for column_name in [
        "updated_at",
        "error",
        "results_json",
        "result_preview",
        "node_summary_json",
        "duration_ms",
        "completed_at",
        "created_at",
        "workflow_name",
        "workflow_id",
        "status",
    ]:
        if column_name in columns:
            op.drop_column("task_runs", column_name)
