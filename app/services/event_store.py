"""Event-store service – append-only event log with state derivation."""

from __future__ import annotations

from typing import Callable, cast

from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import (
    ErrorInfo,
    ExecutionEvent,
    NodeOutput,
    ResolvedInput,
)

SessionFactory = Callable[[], Session]


class EventStore:
    """Synchronous event store backed by PostgreSQL.

    Events are immutable records.  The current state of a workflow run is
    derived by replaying completed events in sequence order.
    """

    def __init__(self, *, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory
        self._publish_callback: Callable[[ExecutionEvent], None] | None = None

    def set_publish_callback(self, callback: Callable[[ExecutionEvent], None]) -> None:
        """Set an optional callback invoked after every append (for WebSocket fan-out)."""
        self._publish_callback = callback

    # -- write ---------------------------------------------------------------

    def append(self, event: ExecutionEvent) -> None:
        """Insert an immutable event into the PostgreSQL log."""
        record = ExecutionEventRecord(
            event_id=event.event_id,
            workflow_run_id=event.workflow_run_id,
            node_id=event.node_id,
            node_type=event.node_type,
            event_type=event.event_type,
            sequence=event.sequence,
            timestamp=event.timestamp,
            output=event.output.model_dump(mode="json") if event.output is not None else None,
            resolved_inputs=(
                {k: v.model_dump(mode="json") for k, v in event.resolved_inputs.items()}
                if event.resolved_inputs
                else None
            ),
            error=event.error.model_dump(mode="json") if event.error is not None else None,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()

        # Fan-out to WebSocket clients
        if self._publish_callback is not None:
            try:
                self._publish_callback(event)
            except Exception:
                pass  # Don't let WS errors break the event pipeline

    # -- reads ---------------------------------------------------------------

    def delete_events_for_nodes(self, workflow_run_id: str, node_ids: set[str]) -> int:
        """Delete events for specific nodes within a run (used by retry).

        Returns the number of deleted records.
        """
        from sqlalchemy import delete as sa_delete

        with self._session_factory() as session:
            result = session.execute(
                sa_delete(ExecutionEventRecord).where(
                    ExecutionEventRecord.workflow_run_id == workflow_run_id,
                    ExecutionEventRecord.node_id.in_(node_ids),
                )
            )
            session.commit()
            return int(cast(CursorResult[object], result).rowcount or 0)

    def delete_events(self, workflow_run_id: str) -> int:
        """Delete all events for a run (used by reset)."""
        from sqlalchemy import delete as sa_delete

        with self._session_factory() as session:
            result = session.execute(
                sa_delete(ExecutionEventRecord).where(
                    ExecutionEventRecord.workflow_run_id == workflow_run_id,
                )
            )
            session.commit()
            return int(cast(CursorResult[object], result).rowcount or 0)

    def get_events(self, workflow_run_id: str) -> list[ExecutionEvent]:
        """Read all events for a run, ordered by sequence."""
        with self._session_factory() as session:
            records = (
                session.execute(
                    select(ExecutionEventRecord)
                    .where(ExecutionEventRecord.workflow_run_id == workflow_run_id)
                    .order_by(ExecutionEventRecord.sequence.asc())
                )
                .scalars()
                .all()
            )
            return [self._to_model(r) for r in records]

    def get_max_sequence(self, workflow_run_id: str) -> int | None:
        """Return the highest sequence number for a run, or None if no events."""
        with self._session_factory() as session:
            result = session.execute(
                select(func.max(ExecutionEventRecord.sequence)).where(
                    ExecutionEventRecord.workflow_run_id == workflow_run_id
                )
            ).scalar()
            return result

    def get_events_from(self, workflow_run_id: str, after_sequence: int) -> list[ExecutionEvent]:
        """Read events with sequence > *after_sequence*.  Used for WebSocket catch-up."""
        with self._session_factory() as session:
            records = (
                session.execute(
                    select(ExecutionEventRecord)
                    .where(
                        ExecutionEventRecord.workflow_run_id == workflow_run_id,
                        ExecutionEventRecord.sequence > after_sequence,
                    )
                    .order_by(ExecutionEventRecord.sequence.asc())
                )
                .scalars()
                .all()
            )
            return [self._to_model(r) for r in records]

    # -- state derivation ----------------------------------------------------

    def compute_state(self, workflow_run_id: str) -> dict[str, NodeOutput]:
        """Derive flatten-JSON state from the full event log.

        Iterates all events in sequence order.  For every *completed* event,
        ``state[node_id]`` is set to the event's ``output``.  The last
        completed event per *node_id* wins, which naturally handles retries.
        """
        events = self.get_events(workflow_run_id)
        return self._derive_state(events)

    def replay_to(self, workflow_run_id: str, sequence: int) -> dict[str, NodeOutput]:
        """Same as :meth:`compute_state` but only considers events with
        ``sequence <= *sequence*``."""
        with self._session_factory() as session:
            records = (
                session.execute(
                    select(ExecutionEventRecord)
                    .where(
                        ExecutionEventRecord.workflow_run_id == workflow_run_id,
                        ExecutionEventRecord.sequence <= sequence,
                    )
                    .order_by(ExecutionEventRecord.sequence.asc())
                )
                .scalars()
                .all()
            )
            events = [self._to_model(r) for r in records]
        return self._derive_state(events)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _derive_state(events: list[ExecutionEvent]) -> dict[str, NodeOutput]:
        state: dict[str, NodeOutput] = {}
        for event in events:
            if event.event_type == "completed" and event.output is not None:
                state[event.node_id] = event.output
        return state

    @staticmethod
    def _to_model(record: ExecutionEventRecord) -> ExecutionEvent:
        """Convert an ORM record to a Pydantic :class:`ExecutionEvent`."""
        output: NodeOutput | None = (
            NodeOutput.model_validate(record.output) if record.output is not None else None
        )

        resolved_inputs: dict[str, ResolvedInput] = {}
        if record.resolved_inputs is not None:
            resolved_inputs = {
                k: ResolvedInput.model_validate(v) for k, v in record.resolved_inputs.items()
            }

        error: ErrorInfo | None = (
            ErrorInfo.model_validate(record.error) if record.error is not None else None
        )

        return ExecutionEvent(
            event_id=record.event_id,
            workflow_run_id=record.workflow_run_id,
            node_id=record.node_id,
            node_type=record.node_type,
            event_type=record.event_type,
            sequence=record.sequence,
            timestamp=record.timestamp,
            output=output,
            resolved_inputs=resolved_inputs,
            error=error,
        )
