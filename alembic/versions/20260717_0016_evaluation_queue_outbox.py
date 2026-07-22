"""Add durable evaluation dispatch and distributed evaluation invariants."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_0016"
down_revision: Union[str, Sequence[str], None] = "20260716_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")}


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _preflight_duplicates() -> None:
    connection = op.get_bind()
    tables = _existing_tables()
    diagnostics: list[str] = []

    if "evaluation_runs" in tables:
        active_rows = connection.execute(
            sa.text(
                "SELECT test_set_id, COUNT(*) AS duplicate_count "
                "FROM evaluation_runs "
                "WHERE status IN ('pending', 'running') "
                "GROUP BY test_set_id HAVING COUNT(*) > 1"
            )
        ).all()
        if active_rows:
            diagnostics.append(
                "active evaluation runs by test_set_id: "
                + ", ".join(f"{row[0]} ({row[1]})" for row in active_rows)
            )

        request_rows = connection.execute(
            sa.text(
                "SELECT test_set_id, client_request_id, COUNT(*) AS duplicate_count "
                "FROM evaluation_runs "
                "WHERE client_request_id IS NOT NULL "
                "GROUP BY test_set_id, client_request_id HAVING COUNT(*) > 1"
            )
        ).all()
        if request_rows:
            diagnostics.append(
                "duplicate client_request_id values: "
                + ", ".join(f"({row[0]}, {row[1]}) ({row[2]})" for row in request_rows)
            )

    if "evaluation_results" in tables:
        result_rows = connection.execute(
            sa.text(
                "SELECT evaluation_run_id, document_id, COUNT(*) AS duplicate_count "
                "FROM evaluation_results "
                "GROUP BY evaluation_run_id, document_id HAVING COUNT(*) > 1"
            )
        ).all()
        if result_rows:
            diagnostics.append(
                "duplicate evaluation results: "
                + ", ".join(f"({row[0]}, {row[1]}) ({row[2]})" for row in result_rows)
            )

    if diagnostics:
        raise RuntimeError(
            "Evaluation queue migration preflight failed; resolve duplicate data before "
            "creating unique indexes: " + "; ".join(diagnostics)
        )


def _create_index_if_missing(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    where: str | None = None,
) -> None:
    if name in _existing_indexes(table_name):
        return
    if where is None:
        op.create_index(name, table_name, columns, unique=unique)
        return
    predicate = sa.text(where)
    op.create_index(
        name,
        table_name,
        columns,
        unique=unique,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def upgrade() -> None:
    _preflight_duplicates()
    tables = _existing_tables()
    if "evaluation_dispatch_outbox" not in tables:
        op.create_table(
            "evaluation_dispatch_outbox",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("evaluation_result_id", sa.Text(), nullable=False),
            sa.Column("task_run_id", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "available_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["evaluation_result_id"],
                ["evaluation_results.id"],
                name="fk_evaluation_dispatch_outbox_result",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_evaluation_dispatch_outbox"),
            sa.UniqueConstraint(
                "evaluation_result_id",
                name="uq_evaluation_dispatch_outbox_result_id",
            ),
            sa.UniqueConstraint("task_run_id", name="uq_evaluation_dispatch_outbox_task_run_id"),
            sa.CheckConstraint(
                "status IN ('pending', 'publishing', 'published', 'cancelled')",
                name="ck_evaluation_dispatch_outbox_status",
            ),
        )

    _create_index_if_missing(
        "idx_evaluation_dispatch_outbox_available",
        "evaluation_dispatch_outbox",
        ["status", "available_at"],
    )
    _create_index_if_missing(
        "idx_evaluation_dispatch_outbox_lease",
        "evaluation_dispatch_outbox",
        ["status", "lease_expires_at"],
    )
    _create_index_if_missing(
        "uq_evaluation_runs_active_test_set",
        "evaluation_runs",
        ["test_set_id"],
        unique=True,
        where="status IN ('pending', 'running')",
    )
    _create_index_if_missing(
        "uq_evaluation_runs_client_request",
        "evaluation_runs",
        ["test_set_id", "client_request_id"],
        unique=True,
        where="client_request_id IS NOT NULL",
    )
    _create_index_if_missing(
        "uq_evaluation_results_run_document",
        "evaluation_results",
        ["evaluation_run_id", "document_id"],
        unique=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    if "evaluation_dispatch_outbox" in _existing_tables():
        count = connection.execute(
            sa.text("SELECT COUNT(*) FROM evaluation_dispatch_outbox")
        ).scalar_one()
        if int(count) > 0:
            raise RuntimeError(
                "Cannot downgrade evaluation queue schema while dispatch outbox rows remain"
            )

    for name, table_name in (
        ("uq_evaluation_results_run_document", "evaluation_results"),
        ("uq_evaluation_runs_client_request", "evaluation_runs"),
        ("uq_evaluation_runs_active_test_set", "evaluation_runs"),
        ("idx_evaluation_dispatch_outbox_lease", "evaluation_dispatch_outbox"),
        ("idx_evaluation_dispatch_outbox_available", "evaluation_dispatch_outbox"),
    ):
        if name in _existing_indexes(table_name):
            op.drop_index(name, table_name=table_name)

    if "evaluation_dispatch_outbox" in _existing_tables():
        op.drop_table("evaluation_dispatch_outbox")
