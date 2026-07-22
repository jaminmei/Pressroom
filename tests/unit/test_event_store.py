from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db.execution_event import ExecutionEventRecord
from app.models.execution import ErrorInfo, ExecutionEvent, NodeOutput, ResolvedInput
from app.services.event_store import EventStore

SessionFactory = Callable[[], Session]


@pytest.fixture()
def store(tmp_path) -> Iterator[tuple[EventStore, SessionFactory]]:
    db_path = tmp_path / "event_store_test.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    metadata = MetaData()
    ExecutionEventRecord.__table__.to_metadata(metadata)
    with engine.begin() as conn:
        metadata.create_all(conn)

    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield EventStore(session_factory=session_factory), session_factory
    engine.dispose()


def _make_event(
    *,
    event_id: str = "evt-001",
    run_id: str = "run-1",
    node_id: str = "node-1",
    node_type: str = "engine",
    event_type: str = "completed",
    sequence: int = 1,
    output: NodeOutput | None = None,
    error: ErrorInfo | None = None,
    resolved_inputs: dict[str, ResolvedInput] | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        workflow_run_id=run_id,
        node_id=node_id,
        node_type=node_type,
        event_type=event_type,
        sequence=sequence,
        timestamp=1713945600.0 + sequence,
        output=output,
        error=error,
        resolved_inputs=resolved_inputs or {},
    )


class TestAppend:
    def test_append_and_read_back(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        event = _make_event(output=NodeOutput(text="hello"))
        es.append(event)

        events = es.get_events("run-1")
        assert len(events) == 1
        assert events[0].event_id == "evt-001"
        assert events[0].output is not None
        assert events[0].output.text == "hello"

    def test_append_multiple_events_ordered(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        for i in range(5):
            es.append(_make_event(event_id=f"evt-{i:03d}", sequence=i + 1))

        events = es.get_events("run-1")
        assert len(events) == 5
        assert [e.sequence for e in events] == [1, 2, 3, 4, 5]

    def test_append_with_error(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        event = _make_event(
            event_type="failed",
            output=None,
            error=ErrorInfo(
                type="TimeoutError", message="timed out", retry_count=1, is_retryable=True
            ),
        )
        es.append(event)

        events = es.get_events("run-1")
        assert events[0].event_type == "failed"
        assert events[0].error is not None
        assert events[0].error.type == "TimeoutError"
        assert events[0].error.retry_count == 1

    def test_append_with_resolved_inputs(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        ri = ResolvedInput(name="image", source_node_id="upload-1", source_event_id="evt-up-1")
        event = _make_event(
            node_id="ocr-1",
            resolved_inputs={"image": ri},
            output=NodeOutput(text="OCR result"),
        )
        es.append(event)

        events = es.get_events("run-1")
        assert "image" in events[0].resolved_inputs
        assert events[0].resolved_inputs["image"].source_node_id == "upload-1"

    def test_isolation_between_runs(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(_make_event(event_id="evt-A", run_id="run-A", output=NodeOutput(text="A")))
        es.append(_make_event(event_id="evt-B", run_id="run-B", output=NodeOutput(text="B")))

        assert len(es.get_events("run-A")) == 1
        assert len(es.get_events("run-B")) == 1
        assert es.get_events("run-A")[0].output.text == "A"


class TestComputeState:
    def test_empty_run(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        assert es.compute_state("nonexistent") == {}

    def test_single_completed(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                node_id="ocr-1",
                event_type="completed",
                output=NodeOutput(text="OCR result"),
            )
        )
        state = es.compute_state("run-1")
        assert "ocr-1" in state
        assert state["ocr-1"].text == "OCR result"

    def test_started_and_failed_ignored(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(_make_event(event_id="s1", event_type="started", sequence=1, output=None))
        es.append(
            _make_event(
                event_id="s2",
                event_type="failed",
                sequence=2,
                output=None,
                error=ErrorInfo(type="Err", message="fail"),
            )
        )
        state = es.compute_state("run-1")
        assert state == {}

    def test_multiple_nodes(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                event_id="e1", node_id="upload-1", sequence=1, output=NodeOutput(text="image data")
            )
        )
        es.append(
            _make_event(
                event_id="e2", node_id="ocr-1", sequence=2, output=NodeOutput(text="OCR text")
            )
        )
        es.append(
            _make_event(
                event_id="e3", node_id="vlm-1", sequence=3, output=NodeOutput(text="VLM desc")
            )
        )

        state = es.compute_state("run-1")
        assert len(state) == 3
        assert state["upload-1"].text == "image data"
        assert state["ocr-1"].text == "OCR text"
        assert state["vlm-1"].text == "VLM desc"

    def test_retry_overwrites(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                event_id="e1", node_id="ocr-1", sequence=1, event_type="started", output=None
            )
        )
        es.append(
            _make_event(
                event_id="e2",
                node_id="ocr-1",
                sequence=2,
                event_type="failed",
                output=None,
                error=ErrorInfo(type="Err", message="fail"),
            )
        )
        es.append(
            _make_event(
                event_id="e3",
                node_id="ocr-1",
                sequence=3,
                event_type="completed",
                output=NodeOutput(text="retry ok"),
            )
        )

        state = es.compute_state("run-1")
        assert len(state) == 1
        assert state["ocr-1"].text == "retry ok"

    def test_skipped_events_ignored(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                event_id="e1",
                node_id="ocr-1",
                sequence=1,
                event_type="completed",
                output=NodeOutput(text="done"),
            )
        )
        es.append(
            _make_event(
                event_id="e2", node_id="layout-1", sequence=2, event_type="skipped", output=None
            )
        )

        state = es.compute_state("run-1")
        assert "ocr-1" in state
        assert "layout-1" not in state


class TestReplayTo:
    def test_replay_partial(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                event_id="e1", node_id="upload-1", sequence=1, output=NodeOutput(text="img")
            )
        )
        es.append(
            _make_event(event_id="e2", node_id="ocr-1", sequence=2, output=NodeOutput(text="text"))
        )
        es.append(
            _make_event(event_id="e3", node_id="vlm-1", sequence=3, output=NodeOutput(text="desc"))
        )

        state = es.replay_to("run-1", 2)
        assert len(state) == 2
        assert "upload-1" in state
        assert "ocr-1" in state
        assert "vlm-1" not in state

    def test_replay_to_zero(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(
                event_id="e1", node_id="upload-1", sequence=1, output=NodeOutput(text="img")
            )
        )
        assert es.replay_to("run-1", 0) == {}

    def test_replay_exact_sequence(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        es.append(
            _make_event(event_id="e1", node_id="ocr-1", sequence=1, output=NodeOutput(text="first"))
        )
        es.append(
            _make_event(
                event_id="e2", node_id="ocr-1", sequence=2, output=NodeOutput(text="second")
            )
        )

        state = es.replay_to("run-1", 1)
        assert state["ocr-1"].text == "first"

        state = es.replay_to("run-1", 2)
        assert state["ocr-1"].text == "second"


class TestGetEventsFrom:
    def test_get_events_after_sequence(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        for i in range(5):
            es.append(_make_event(event_id=f"e{i}", sequence=i + 1))

        events = es.get_events_from("run-1", 3)
        assert len(events) == 2
        assert events[0].sequence == 4
        assert events[1].sequence == 5

    def test_get_events_from_empty(self, store: tuple[EventStore, SessionFactory]):
        es, _ = store
        assert es.get_events_from("nonexistent", 0) == []
