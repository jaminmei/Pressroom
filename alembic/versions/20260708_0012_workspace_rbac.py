"""Workspace RBAC schema and legacy workspace backfill.

Revision ID: 20260708_0012
Revises: 20260706_0011
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260708_0012"
down_revision: Union[str, Sequence[str], None] = "20260706_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESOURCE_TABLES: tuple[str, ...] = (
    "workflows",
    "test_sets",
    "evaluation_runs",
    "task_runs",
)


def _migrated_ids(table_name: str) -> list[str]:
    bind = op.get_bind()
    return [
        str(row.id)
        for row in bind.execute(
            sa.text(f"SELECT id FROM {table_name} WHERE workspace_id = :workspace_id ORDER BY id"),
            {"workspace_id": "ws_legacy"},
        )
    ]


def _print_migration_report() -> None:
    print("Workspace RBAC migration report")
    for table_name in RESOURCE_TABLES:
        ids = _migrated_ids(table_name)
        print(f"{table_name}: {', '.join(ids) if ids else '(none)'}")


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_workspaces_owner_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_members_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_workspace_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspace_members"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_members_workspace_id_user_id",
        ),
    )
    op.create_index("idx_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index("idx_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("idx_workspace_members_user_id", "workspace_members", ["user_id"])

    workspace_column = (
        sa.Column("workspace_id", sa.Text(), nullable=True)
        if bind.dialect.name == "sqlite"
        else sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id"), nullable=True)
    )
    for table_name in RESOURCE_TABLES:
        op.add_column(
            table_name,
            workspace_column.copy(),
        )
    last_workspace_column = (
        sa.Column("last_workspace_id", sa.Text(), nullable=True)
        if bind.dialect.name == "sqlite"
        else sa.Column(
            "last_workspace_id",
            sa.Text(),
            sa.ForeignKey("workspaces.id"),
            nullable=True,
        )
    )
    op.add_column(
        "users",
        last_workspace_column,
    )

    op.create_index("idx_workflows_workspace_id", "workflows", ["workspace_id"])
    op.create_index("idx_test_sets_workspace_id", "test_sets", ["workspace_id"])
    op.create_index("idx_evaluation_runs_workspace_id", "evaluation_runs", ["workspace_id"])
    op.create_index("idx_task_runs_workspace_id", "task_runs", ["workspace_id"])
    op.create_index("idx_users_last_workspace_id", "users", ["last_workspace_id"])

    owner_user_id = bind.execute(
        sa.text("SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1")
    ).scalar_one_or_none()
    if owner_user_id is None:
        print("Workspace RBAC migration warning: no users found; Legacy Workspace backfill skipped")
        _print_migration_report()
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, owner_user_id)
            VALUES (:id, :name, :owner_user_id)
            """
        ),
        {"id": "ws_legacy", "name": "Legacy Workspace", "owner_user_id": owner_user_id},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO workspace_members (id, workspace_id, user_id, role)
            VALUES (:id, :workspace_id, :user_id, :role)
            """
        ),
        {
            "id": "wsm_legacy_owner",
            "workspace_id": "ws_legacy",
            "user_id": owner_user_id,
            "role": "owner",
        },
    )
    bind.execute(
        sa.text("UPDATE workflows SET workspace_id='ws_legacy' WHERE workspace_id IS NULL")
    )
    bind.execute(
        sa.text("UPDATE test_sets SET workspace_id='ws_legacy' WHERE workspace_id IS NULL")
    )
    bind.execute(
        sa.text("UPDATE task_runs SET workspace_id='ws_legacy' WHERE workspace_id IS NULL")
    )
    bind.execute(
        sa.text(
            """
            UPDATE evaluation_runs
            SET workspace_id = (
                SELECT ts.workspace_id FROM test_sets ts WHERE ts.id = evaluation_runs.test_set_id
            )
            WHERE workspace_id IS NULL
            """
        )
    )
    bind.execute(
        sa.text("UPDATE evaluation_runs SET workspace_id='ws_legacy' WHERE workspace_id IS NULL")
    )

    _print_migration_report()


def downgrade() -> None:
    op.drop_index("idx_users_last_workspace_id", table_name="users")
    op.drop_index("idx_task_runs_workspace_id", table_name="task_runs")
    op.drop_index("idx_evaluation_runs_workspace_id", table_name="evaluation_runs")
    op.drop_index("idx_test_sets_workspace_id", table_name="test_sets")
    op.drop_index("idx_workflows_workspace_id", table_name="workflows")

    op.drop_column("users", "last_workspace_id")
    op.drop_column("task_runs", "workspace_id")
    op.drop_column("evaluation_runs", "workspace_id")
    op.drop_column("test_sets", "workspace_id")
    op.drop_column("workflows", "workspace_id")

    op.drop_index("idx_workspace_members_user_id", table_name="workspace_members")
    op.drop_index("idx_workspace_members_workspace_id", table_name="workspace_members")
    op.drop_index("idx_workspaces_slug", table_name="workspaces")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
