"""Merge the chatbox and Agent Tools migration heads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

revision: str = "20260825_0022"
down_revision: Union[str, Sequence[str], None] = (
    "20260819_0018",
    "20260820_0021",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join both already-applied schema branches without additional DDL."""


def downgrade() -> None:
    """Return to the two parent migration heads without additional DDL."""
