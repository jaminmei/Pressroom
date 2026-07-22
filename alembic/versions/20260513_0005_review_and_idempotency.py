"""Add review fields to evaluation_results and client_request_id to evaluation_runs.

Revision ID: 20260513_0005
Revises: 20260424_0004b
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260513_0005"
down_revision: Union[str, Sequence[str], None] = "20260424_0004b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_columns(table_name: str) -> set[str]:
    """Get existing column names for a table (for idempotent checks)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column[object]) -> None:
    """Add a column only if it doesn't already exist."""
    existing = _get_columns(table_name)
    if column.name not in existing:
        op.add_column(table_name, column)


def upgrade() -> None:
    # --- evaluation_results: review fields ---
    _add_column_if_missing(
        "evaluation_results",
        sa.Column(
            "review_status", sa.Text(), nullable=True, server_default=sa.text("'unreviewed'")
        ),
    )
    _add_column_if_missing(
        "evaluation_results",
        sa.Column("accepted_ground_truth_id", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "evaluation_results",
        sa.Column("reviewed_at", sa.DateTime(timezone=False), nullable=True),
    )
    _add_column_if_missing(
        "evaluation_results",
        sa.Column("reviewed_by", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "evaluation_results",
        sa.Column("review_notes", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "evaluation_results",
        sa.Column(
            "comparison_status", sa.Text(), nullable=True, server_default=sa.text("'not_compared'")
        ),
    )

    # --- evaluation_runs: idempotency key ---
    _add_column_if_missing(
        "evaluation_runs",
        sa.Column("client_request_id", sa.Text(), nullable=True),
    )

    # Index for client_request_id lookups (unique per test_set context, not globally unique)
    try:
        op.create_index(
            "idx_evaluation_runs_client_request_id",
            "evaluation_runs",
            ["client_request_id"],
            unique=False,
        )
    except Exception:
        pass  # Index may already exist

    # Index for review_status filtering
    try:
        op.create_index(
            "idx_evaluation_results_review_status",
            "evaluation_results",
            ["review_status"],
            unique=False,
        )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index("idx_evaluation_results_review_status", table_name="evaluation_results")
    op.drop_index("idx_evaluation_runs_client_request_id", table_name="evaluation_runs")
    op.drop_column("evaluation_runs", "client_request_id")
    op.drop_column("evaluation_results", "comparison_status")
    op.drop_column("evaluation_results", "review_notes")
    op.drop_column("evaluation_results", "reviewed_by")
    op.drop_column("evaluation_results", "reviewed_at")
    op.drop_column("evaluation_results", "accepted_ground_truth_id")
    op.drop_column("evaluation_results", "review_status")
