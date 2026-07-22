"""Create evaluation suite persistence schema."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424_0004b"
down_revision: Union[str, Sequence[str], None] = "20260424_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column[object]) -> None:
    if column.name in _get_columns(table_name):
        return
    op.add_column(table_name, column)


def upgrade() -> None:
    op.create_table(
        "test_sets",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.PrimaryKeyConstraint("id", name="pk_test_sets"),
    )

    op.create_table(
        "test_documents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("test_set_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["test_set_id"],
            ["test_sets.id"],
            name="fk_test_documents_test_set_id_test_sets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_documents"),
    )
    op.create_index(
        "idx_test_documents_storage_path",
        "test_documents",
        ["storage_path"],
        unique=True,
    )
    op.create_index(
        "idx_test_documents_test_set_id",
        "test_documents",
        ["test_set_id"],
        unique=False,
    )

    op.create_table(
        "ground_truths",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False, server_default=sa.text("'text'")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_task_run_id", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["test_documents.id"],
            name="fk_ground_truths_document_id_test_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ground_truths"),
        sa.UniqueConstraint("document_id", "version", name="uq_ground_truths_document_id_version"),
    )
    op.create_index("idx_ground_truths_document_id", "ground_truths", ["document_id"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("test_set_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=True),
        sa.Column("workflow_snapshot_json", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("total_documents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["test_set_id"],
            ["test_sets.id"],
            name="fk_evaluation_runs_test_set_id_test_sets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_runs"),
    )
    op.create_index(
        "idx_evaluation_runs_test_set_id",
        "evaluation_runs",
        ["test_set_id"],
        unique=False,
    )
    op.create_index(
        "idx_evaluation_runs_workflow_id",
        "evaluation_runs",
        ["workflow_id"],
        unique=False,
    )

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("evaluation_run_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("task_run_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("output_content", sa.Text(), nullable=True),
        sa.Column("output_format", sa.Text(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["test_documents.id"],
            name="fk_evaluation_results_document_id_test_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_evaluation_results_evaluation_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_run_id"],
            ["task_runs.id"],
            name="fk_evaluation_results_task_run_id_task_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_results"),
    )
    op.create_index(
        "idx_evaluation_results_run_id",
        "evaluation_results",
        ["evaluation_run_id"],
        unique=False,
    )
    op.create_index(
        "idx_evaluation_results_document_id",
        "evaluation_results",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "uq_evaluation_results_task_run_id",
        "evaluation_results",
        ["task_run_id"],
        unique=True,
    )

    _add_column_if_missing("task_runs", sa.Column("run_name", sa.Text(), nullable=True))
    _add_column_if_missing(
        "task_runs",
        sa.Column("source", sa.Text(), nullable=True, server_default=sa.text("'manual'")),
    )
    _add_column_if_missing("task_runs", sa.Column("evaluation_run_id", sa.Text(), nullable=True))
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_fks = {
        str(fk.get("name")) for fk in inspector.get_foreign_keys("task_runs") if fk.get("name")
    }
    if (
        bind.dialect.name != "sqlite"
        and "fk_task_runs_evaluation_run_id_evaluation_runs" not in existing_fks
    ):
        op.create_foreign_key(
            "fk_task_runs_evaluation_run_id_evaluation_runs",
            "task_runs",
            "evaluation_runs",
            ["evaluation_run_id"],
            ["id"],
        )


def downgrade() -> None:
    existing = _get_columns("task_runs")
    if "evaluation_run_id" in existing:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        existing_fks = {
            str(fk.get("name")) for fk in inspector.get_foreign_keys("task_runs") if fk.get("name")
        }
        if (
            bind.dialect.name != "sqlite"
            and "fk_task_runs_evaluation_run_id_evaluation_runs" in existing_fks
        ):
            op.drop_constraint(
                "fk_task_runs_evaluation_run_id_evaluation_runs",
                "task_runs",
                type_="foreignkey",
            )

    op.drop_index("uq_evaluation_results_task_run_id", table_name="evaluation_results")
    op.drop_index("idx_evaluation_results_document_id", table_name="evaluation_results")
    op.drop_index("idx_evaluation_results_run_id", table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index("idx_evaluation_runs_workflow_id", table_name="evaluation_runs")
    op.drop_index("idx_evaluation_runs_test_set_id", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_index("idx_ground_truths_document_id", table_name="ground_truths")
    op.drop_table("ground_truths")
    op.drop_index("idx_test_documents_test_set_id", table_name="test_documents")
    op.drop_index("idx_test_documents_storage_path", table_name="test_documents")
    op.drop_table("test_documents")
    op.drop_table("test_sets")

    for column_name in ["evaluation_run_id", "source", "run_name"]:
        if column_name in existing:
            op.drop_column("task_runs", column_name)
