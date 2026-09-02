"""Backfill stable navigation metadata for legacy Agent Sessions."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0025"
down_revision: Union[str, Sequence[str], None] = "20260826_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHITESPACE = re.compile(r"\s+")
_TITLE_LIMIT = 72
_PREVIEW_LIMIT = 180


def _navigation_metadata(raw_messages: Any) -> tuple[str, str] | None:
    if isinstance(raw_messages, str):
        try:
            raw_messages = json.loads(raw_messages)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw_messages, list):
        return None

    texts: list[str] = []
    for message in raw_messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        text = " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        normalized = _WHITESPACE.sub(" ", text).strip()
        if normalized:
            texts.append(normalized)
        if len(texts) >= 2:
            break
    if not texts:
        return None

    seed = texts[0]
    title = seed if len(seed) <= _TITLE_LIMIT else f"{seed[: _TITLE_LIMIT - 1].rstrip()}…"
    preview_source = " — ".join(texts)
    preview = (
        preview_source
        if len(preview_source) <= _PREVIEW_LIMIT
        else f"{preview_source[: _PREVIEW_LIMIT - 1].rstrip()}…"
    )
    return title, preview


def upgrade() -> None:
    connection = op.get_bind()
    sessions = connection.execute(
        sa.text(
            """
            SELECT id, messages_json, title, preview
            FROM chatbox_sessions
            WHERE title IS NULL OR preview IS NULL
            """
        )
    ).mappings()
    for session in sessions:
        metadata = _navigation_metadata(session["messages_json"])
        if metadata is None:
            continue
        title, preview = metadata
        connection.execute(
            sa.text(
                """
                UPDATE chatbox_sessions
                SET title = COALESCE(title, :title),
                    preview = COALESCE(preview, :preview)
                WHERE id = :session_id
                """
            ),
            {"session_id": session["id"], "title": title, "preview": preview},
        )


def downgrade() -> None:
    # Existing and backfilled navigation strings are intentionally
    # indistinguishable, so a downgrade must preserve both.
    pass
