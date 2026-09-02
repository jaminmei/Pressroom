"""Authoritative browser-safe chatbox snapshots and reconnect journal."""

from __future__ import annotations

import copy
import uuid
from collections import deque
from datetime import datetime
from typing import Any

from app.db.session import SessionLocal
from app.models.db.chatbox_session import ChatboxSession
from app.services.agent_sessions import derive_navigation_metadata

_MAX_MESSAGES = 200
_MAX_TOOL_EXECUTIONS = 200
_MAX_COMPACTION_NOTES = 50
_MAX_PENDING_EVENTS = 4_096
_PLACEHOLDER = {"type": "placeholder"}
_PERSIST_EVENT_TYPES = {
    "agent_start",
    "agent_settled",
    "message_end",
    "tool_execution_end",
    "compaction_end",
}


class ChatboxHistoryStaleError(RuntimeError):
    """The requested revision can no longer be replayed from memory."""


class ChatboxHistory:
    """Single-consumer snapshot reducer with a bounded reconnect journal.

    Deltas update the in-memory snapshot and journal only. Terminal events
    commit the whole projected snapshot and revision, avoiding a database
    write for every streamed token while retaining an atomic reconnect point.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        with SessionLocal() as database:
            session = database.get(ChatboxSession, session_id)
            if session is None:
                raise LookupError("Chatbox session not found")
            self.messages = copy.deepcopy(session.messages_json or [])
            self.tool_executions = copy.deepcopy(session.tool_executions_json or {})
            self.compaction_notes = copy.deepcopy(session.compaction_notes_json or [])
            self.live_message_id = session.live_message_id
            self.revision = session.snapshot_revision
        self.persisted_revision = self.revision
        self._journal: deque[tuple[int, dict[str, object]]] = deque(maxlen=_MAX_PENDING_EVENTS)

    def apply(self, event: dict[str, object]) -> tuple[int, dict[str, object]]:
        """Apply one already-projected event and assign stable message ids."""

        browser_event = copy.deepcopy(event)
        self.revision += 1
        event_type = browser_event.get("type")

        if event_type in {"message_start", "message_end"}:
            self._apply_message_boundary(browser_event, str(event_type))
        elif event_type == "message_update" and self.live_message_id is not None:
            _apply_message_delta(self.messages, self.live_message_id, browser_event)
        elif event_type in {
            "tool_execution_start",
            "tool_execution_update",
            "tool_execution_end",
        }:
            _apply_tool_event(self.tool_executions, browser_event)
        elif event_type == "compaction_end":
            result = browser_event.get("result")
            summary = result.get("summary") if isinstance(result, dict) else None
            self.compaction_notes.append(
                {
                    "id": f"compaction-{uuid.uuid4().hex}",
                    "kind": "compaction",
                    "summary": summary if isinstance(summary, str) else None,
                    "aborted": browser_event.get("aborted") is True,
                }
            )
        elif event_type == "agent_settled":
            self.live_message_id = None

        self._journal.append((self.revision, browser_event))
        if event_type in _PERSIST_EVENT_TYPES:
            lifecycle = (
                "active"
                if event_type == "agent_start"
                else "idle"
                if event_type == "agent_settled"
                else None
            )
            runtime_state = (
                "running"
                if event_type == "agent_start"
                else "idle"
                if event_type == "agent_settled"
                else None
            )
            self._persist(
                lifecycle, runtime_state=runtime_state, settled=event_type == "agent_settled"
            )
        return self.revision, browser_event

    def pending_after(self, revision: int) -> list[dict[str, object]]:
        """Return ordered native Pi frames after a REST snapshot revision."""

        if revision < self.persisted_revision or revision > self.revision:
            raise ChatboxHistoryStaleError
        if self._journal and revision < self._journal[0][0] - 1:
            raise ChatboxHistoryStaleError
        return [
            copy.deepcopy(event)
            for item_revision, event in self._journal
            if item_revision > revision
        ]

    def mark_dead(self) -> None:
        """Atomically retain the last projected snapshot and mark the runtime dead."""

        self.revision += 1
        self._persist("dead", runtime_state="failed")

    def checkpoint(
        self,
        *,
        runtime_state: str | None = None,
        session_state: str | None = None,
        navigation_ready: bool = False,
    ) -> None:
        """Persist the current in-memory reducer state and journal revision."""

        self._persist(
            None,
            runtime_state=runtime_state,
            session_state=session_state,
            navigation_ready=navigation_ready,
        )

    def _apply_message_boundary(self, event: dict[str, object], event_type: str) -> None:
        raw_message = event.get("message")
        if not isinstance(raw_message, dict):
            return
        message_id = raw_message.get("id")
        if event_type == "message_end" and self.live_message_id is not None:
            # Pi's native start/end messages commonly have no id. Even if an
            # SDK version changes a terminal id, the active start is the same
            # ordered message and remains authoritative for browser upsert.
            message_id = self.live_message_id
            raw_message["id"] = message_id
        elif not isinstance(message_id, str) or not message_id:
            message_id = f"pi-message-{uuid.uuid4().hex}"
            raw_message["id"] = message_id
        snapshot_message = _normalize_message(raw_message, message_id)
        existing_index = _message_index(self.messages, message_id)
        if (
            event_type == "message_end"
            and not snapshot_message["content"]
            and existing_index is not None
        ):
            snapshot_message["content"] = _without_placeholders(
                self.messages[existing_index].get("content")
            )
        if existing_index is None:
            self.messages.append(snapshot_message)
        else:
            self.messages[existing_index] = snapshot_message
        self.live_message_id = message_id if event_type == "message_start" else None

    def _persist(
        self,
        lifecycle_state: str | None,
        *,
        runtime_state: str | None = None,
        session_state: str | None = None,
        settled: bool = False,
        navigation_ready: bool = False,
    ) -> None:
        with SessionLocal() as database:
            session = database.get(ChatboxSession, self.session_id)
            if session is None:
                raise LookupError(f"Chatbox session {self.session_id} disappeared before persist")
            session.messages_json = copy.deepcopy(self.messages[-_MAX_MESSAGES:])
            session.tool_executions_json = copy.deepcopy(
                dict(list(self.tool_executions.items())[-_MAX_TOOL_EXECUTIONS:])
            )
            session.compaction_notes_json = copy.deepcopy(
                self.compaction_notes[-_MAX_COMPACTION_NOTES:]
            )
            session.live_message_id = self.live_message_id
            session.snapshot_revision = self.revision
            if lifecycle_state is not None:
                session.lifecycle_state = lifecycle_state
            if runtime_state is not None:
                session.runtime_state = runtime_state
            if session_state is not None:
                session.session_state = session_state
            now = datetime.now()
            if settled or navigation_ready:
                session.last_activity_at = now
            if settled:
                if session.first_settled_at is None:
                    session.first_settled_at = now
            if settled or navigation_ready:
                if session.title is None or session.preview is None:
                    title, preview = derive_navigation_metadata(session.messages_json)
                    session.title = session.title or title
                    session.preview = session.preview or preview
            session.updated_at = now
            database.commit()
        self.persisted_revision = self.revision
        self._journal.clear()


def _normalize_message(message: dict[str, object], message_id: str) -> dict[str, Any]:
    normalized: dict[str, Any] = copy.deepcopy(message)
    normalized["id"] = message_id
    content = normalized.get("content")
    if isinstance(content, str):
        normalized["content"] = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        normalized["content"] = [
            copy.deepcopy(block) for block in content if isinstance(block, dict)
        ]
    else:
        normalized["content"] = []
    return normalized


def _message_index(messages: list[dict[str, Any]], message_id: str) -> int | None:
    return next(
        (index for index, message in enumerate(messages) if message.get("id") == message_id),
        None,
    )


def _without_placeholders(content: object) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [
        copy.deepcopy(block)
        for block in content
        if isinstance(block, dict) and block.get("type") != "placeholder"
    ]


def _apply_message_delta(
    messages: list[dict[str, Any]],
    live_message_id: str,
    event: dict[str, object],
) -> None:
    index = _message_index(messages, live_message_id)
    delta_event = event.get("assistantMessageEvent")
    if index is None or not isinstance(delta_event, dict):
        return
    content_index = delta_event.get("contentIndex")
    delta_type = delta_event.get("type")
    delta = delta_event.get("delta")
    if (
        not isinstance(content_index, int)
        or not isinstance(delta_type, str)
        or not isinstance(delta, str)
    ):
        return
    content = messages[index].get("content")
    blocks = copy.deepcopy(content) if isinstance(content, list) else []
    while len(blocks) <= content_index:
        blocks.append(copy.deepcopy(_PLACEHOLDER))
    current = blocks[content_index] if isinstance(blocks[content_index], dict) else {}
    if delta_type == "text_delta":
        prefix = current.get("text") if current.get("type") == "text" else ""
        blocks[content_index] = {"type": "text", "text": f"{prefix}{delta}"}
    elif delta_type == "thinking_delta":
        prefix = current.get("thinking") if current.get("type") == "thinking" else ""
        blocks[content_index] = {"type": "thinking", "thinking": f"{prefix}{delta}"}
    elif delta_type == "toolcall_delta":
        prior_input = current.get("input") if current.get("type") == "toolCall" else None
        if isinstance(prior_input, str):
            updated_input: object = f"{prior_input}{delta}"
        else:
            updated_input = prior_input if prior_input is not None else delta
        blocks[content_index] = {
            "type": "toolCall",
            "toolCallId": current.get("toolCallId", ""),
            "toolName": current.get("toolName", ""),
            "input": updated_input,
        }
    messages[index]["content"] = blocks


def _apply_tool_event(
    tools: dict[str, dict[str, Any]],
    event: dict[str, object],
) -> None:
    call_id = event.get("toolCallId")
    tool_name = event.get("toolName")
    if not isinstance(call_id, str) or not isinstance(tool_name, str):
        return
    current = copy.deepcopy(tools.get(call_id, {"toolCallId": call_id, "toolName": tool_name}))
    if "args" in event:
        current["args"] = copy.deepcopy(event["args"])
    if event.get("type") == "tool_execution_update":
        current["partialResult"] = copy.deepcopy(event.get("partialResult"))
    elif event.get("type") == "tool_execution_end":
        current["result"] = copy.deepcopy(event.get("result"))
        current["isError"] = event.get("isError") is True
    tools[call_id] = current
