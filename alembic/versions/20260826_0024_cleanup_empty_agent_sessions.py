"""Remove abandoned empty Agent Sessions created by the old eager UI flow."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0024"
down_revision: Union[str, Sequence[str], None] = "20260825_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deliberately conservative: title is not used as a deletion predicate.
    # Any message, tool projection, compaction note, live message, settled turn,
    # or durable checkpoint preserves the Session.
    op.execute(
        sa.text(
            """
            DELETE FROM chatbox_sessions
            WHERE session_state IN ('draft', 'paused')
              AND first_settled_at IS NULL
              AND checkpoint_ref IS NULL
              AND live_message_id IS NULL
              AND snapshot_revision = 0
              AND REPLACE(CAST(messages_json AS TEXT), ' ', '') = '[]'
              AND REPLACE(CAST(tool_executions_json AS TEXT), ' ', '') = '{}'
              AND REPLACE(CAST(compaction_notes_json AS TEXT), ' ', '') = '[]'
            """
        )
    )


def downgrade() -> None:
    # Deleted empty shells contain no user content and cannot be reconstructed.
    pass
