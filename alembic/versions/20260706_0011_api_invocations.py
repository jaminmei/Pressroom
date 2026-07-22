"""Add api_invocations for API Forward usage observability.

Revision ID: 20260706_0011
Revises: 20260624_0010
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0011"
down_revision: Union[str, Sequence[str], None] = "20260624_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_invocations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("api_key_prefix", sa.Text(), nullable=True),
        sa.Column("endpoint_kind", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("workflow_status", sa.Text(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("input_metadata_json", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_invocations"),
    )
    op.create_index(
        "idx_api_invocations_workflow_created",
        "api_invocations",
        ["workflow_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_api_invocations_run_id",
        "api_invocations",
        ["workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "idx_api_invocations_key_id",
        "api_invocations",
        ["api_key_id"],
        unique=False,
    )

    bind = op.get_bind()
    error_json_expr = (
        "error"
        if bind.dialect.name == "sqlite"
        else "json_build_object('code', 'LEGACY_ERROR', 'message', error)::text"
    )

    # Compatibility backfill: public API runs created before this table existed
    # have workflow_id but did not persist source/api metadata. Manual editor
    # runs are excluded by source='manual'.
    op.execute(
        f"""
        INSERT INTO api_invocations (
            id,
            workflow_id,
            workflow_run_id,
            endpoint_kind,
            http_status,
            workflow_status,
            response_time_ms,
            input_metadata_json,
            error_json,
            storage_bytes,
            created_at,
            finished_at,
            updated_at
        )
        SELECT
            'legacy_' || id,
            workflow_id,
            id,
            'legacy_unknown',
            CASE
                WHEN status IN ('completed', 'partial_completed', 'failed', 'cancelled') THEN 200
                ELSE NULL
            END,
            COALESCE(status, 'unknown'),
            duration_ms,
            input_files_json,
            CASE
                WHEN error IS NULL THEN NULL
                ELSE {error_json_expr}
            END,
            0,
            COALESCE(created_at, CURRENT_TIMESTAMP),
            completed_at,
            COALESCE(updated_at, completed_at, created_at, CURRENT_TIMESTAMP)
        FROM task_runs
        WHERE workflow_id IS NOT NULL
          AND (source IS NULL OR source = '')
        """
    )


def downgrade() -> None:
    op.drop_index("idx_api_invocations_key_id", table_name="api_invocations")
    op.drop_index("idx_api_invocations_run_id", table_name="api_invocations")
    op.drop_index("idx_api_invocations_workflow_created", table_name="api_invocations")
    op.drop_table("api_invocations")
