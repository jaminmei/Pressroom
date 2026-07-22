"""Create api_keys table

Revision ID: 20260624_0010
Revises: 20260520_0009
"""

import sqlalchemy as sa

from alembic import op

revision = "20260624_0010"
down_revision = "20260520_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("key_prefix", sa.Text, nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index("idx_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("idx_api_keys_workflow_id", "api_keys", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("idx_api_keys_workflow_id", "api_keys")
    op.drop_index("idx_api_keys_key_hash", "api_keys")
    op.drop_table("api_keys")
