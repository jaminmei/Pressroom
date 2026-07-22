"""Create auth and durable workflow persistence tables."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260319_0003"
down_revision: Union[str, Sequence[str], None] = "20260304_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("session_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
    )
    op.create_index(
        "idx_auth_sessions_token_hash", "auth_sessions", ["session_token_hash"], unique=True
    )
    op.create_index("idx_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)

    op.create_table(
        "workflows",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workflow_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_definition_json", sa.JSON(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("last_saved_by_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_workflows_created_by_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["last_saved_by_user_id"],
            ["users.id"],
            name="fk_workflows_last_saved_by_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflows"),
    )
    op.create_index("idx_workflows_workflow_key", "workflows", ["workflow_key"], unique=True)
    op.create_index("idx_workflows_updated_at", "workflows", ["updated_at"], unique=False)

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_workflow_versions_created_by_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name="fk_workflow_versions_workflow_id_workflows",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_versions"),
        sa.UniqueConstraint(
            "workflow_id",
            "version",
            name="uq_workflow_versions_workflow_id_version",
        ),
    )
    op.create_index(
        "idx_workflow_versions_workflow_id",
        "workflow_versions",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_index("idx_workflows_updated_at", table_name="workflows")
    op.drop_index("idx_workflows_workflow_key", table_name="workflows")
    op.drop_table("workflows")
    op.drop_index("idx_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
