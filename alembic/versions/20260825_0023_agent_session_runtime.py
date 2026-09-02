"""Add multi-session state, checkpoint, credential, and approval records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_0023"
down_revision: Union[str, Sequence[str], None] = "20260825_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chatbox_sessions") as batch_op:
        batch_op.add_column(sa.Column("title", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("preview", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("session_state", sa.Text(), nullable=False, server_default=sa.text("'draft'"))
        )
        batch_op.add_column(
            sa.Column(
                "runtime_state", sa.Text(), nullable=False, server_default=sa.text("'stopped'")
            )
        )
        batch_op.add_column(
            sa.Column(
                "runtime_generation", sa.Integer(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(sa.Column("checkpoint_ref", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "checkpoint_revision", sa.Integer(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(
            sa.Column(
                "checkpoint_schema_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(sa.Column("checkpoint_hash", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("first_settled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "last_activity_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch_op.create_check_constraint(
            "ck_chatbox_sessions_session_state",
            "session_state IN ('draft', 'active', 'paused', 'archived')",
        )
        batch_op.create_check_constraint(
            "ck_chatbox_sessions_runtime_state",
            "runtime_state IN ('stopped', 'starting', 'idle', 'running', 'failed')",
        )
    op.create_index(
        "idx_chatbox_sessions_user_workspace_activity",
        "chatbox_sessions",
        ["user_id", "workspace_id", "last_activity_at"],
    )

    op.create_table(
        "chatbox_session_selections",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chatbox_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "workspace_id", name="uq_chatbox_session_selections_user_workspace"
        ),
    )

    op.create_table(
        "agent_session_credentials",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("agent_session_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("runtime_generation", sa.Integer(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False, server_default=sa.text("'agent-session'")),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("hash_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "credential_state", sa.Text(), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "issued_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "credential_state IN ('active', 'expired', 'revoked')",
            name="ck_agent_session_credentials_credential_state",
        ),
        sa.ForeignKeyConstraint(["agent_session_id"], ["chatbox_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_agent_session_credentials_token_hash",
        "agent_session_credentials",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "idx_agent_session_credentials_session_generation",
        "agent_session_credentials",
        ["agent_session_id", "runtime_generation"],
    )
    op.create_index(
        "idx_agent_session_credentials_user_id", "agent_session_credentials", ["user_id"]
    )

    op.create_table(
        "tool_approval_requests",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("agent_session_id", sa.Text(), nullable=False),
        sa.Column("runtime_generation", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("argument_digest", sa.Text(), nullable=False),
        sa.Column("argument_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired', 'executed')",
            name="ck_tool_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_session_id"], ["chatbox_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tool_approval_requests_session_status",
        "tool_approval_requests",
        ["agent_session_id", "status"],
    )
    op.create_index("idx_tool_approval_requests_expiry", "tool_approval_requests", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_tool_approval_requests_expiry", table_name="tool_approval_requests")
    op.drop_index("idx_tool_approval_requests_session_status", table_name="tool_approval_requests")
    op.drop_table("tool_approval_requests")
    op.drop_index("idx_agent_session_credentials_user_id", table_name="agent_session_credentials")
    op.drop_index(
        "idx_agent_session_credentials_session_generation", table_name="agent_session_credentials"
    )
    op.drop_index(
        "idx_agent_session_credentials_token_hash", table_name="agent_session_credentials"
    )
    op.drop_table("agent_session_credentials")
    op.drop_table("chatbox_session_selections")
    op.drop_index("idx_chatbox_sessions_user_workspace_activity", table_name="chatbox_sessions")
    with op.batch_alter_table("chatbox_sessions") as batch_op:
        batch_op.drop_constraint("ck_chatbox_sessions_runtime_state", type_="check")
        batch_op.drop_constraint("ck_chatbox_sessions_session_state", type_="check")
        for column in (
            "archived_at",
            "last_activity_at",
            "first_settled_at",
            "checkpoint_hash",
            "checkpoint_schema_version",
            "checkpoint_revision",
            "checkpoint_ref",
            "runtime_generation",
            "runtime_state",
            "session_state",
            "preview",
            "title",
        ):
            batch_op.drop_column(column)
