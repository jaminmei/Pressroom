"""Remove obsolete user-managed CLI tokens."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0026"
down_revision: Union[str, Sequence[str], None] = "20260826_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_tokens"):
        op.drop_table("user_tokens")


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_tokens"):
        return
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), server_default=sa.text("'cli'"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("hash_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_tokens_token_hash", "user_tokens", ["token_hash"], unique=True)
    op.create_index("idx_user_tokens_user_id", "user_tokens", ["user_id"], unique=False)
    op.create_index("idx_user_tokens_prefix", "user_tokens", ["prefix"], unique=False)
