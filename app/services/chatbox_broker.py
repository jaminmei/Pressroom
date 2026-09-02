"""Server-owned Pi event pump with bounded reconnect replay."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ParamSpec, TypeVar

from app.services.chatbox_history import ChatboxHistory, ChatboxHistoryStaleError
from app.services.chatbox_projection import project_event
from app.services.pi_runtime import PiRuntimeError, PiRuntimeHandle

logger = logging.getLogger(__name__)

_SUBSCRIBER_QUEUE_SIZE = 4_097
_DISCONNECTED_GRACE_SECONDS = 300.0


class ChatboxBrokerBusyError(RuntimeError):
    """A browser already owns the broker's single subscriber slot."""


class ChatboxBrokerResyncError(RuntimeError):
    """The browser must reload its REST snapshot before reconnecting."""


BrokerItem = dict[str, object] | ChatboxBrokerResyncError | PiRuntimeError
_P = ParamSpec("_P")
_T = TypeVar("_T")


async def _run_history_operation(
    operation: Callable[_P, _T],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _T:
    """Run blocking history I/O without letting cancellation outlive its caller."""

    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # asyncio.to_thread cannot stop a thread that has begun executing. Keep
        # the wrapper task shielded, retrieve its result, and only then let the
        # broker stop. This preserves Stop/Refresh lifecycle ordering.
        await asyncio.gather(task, return_exceptions=True)
        raise


class ChatboxRuntimeBroker:
    """Continuously consumes one runtime, independent of browser sockets."""

    def __init__(
        self,
        *,
        chatbox_session_id: str,
        runtime: PiRuntimeHandle,
        workspace_root: Path,
        on_terminal: Callable[[bool], Awaitable[None]],
        on_checkpoint: Callable[[], Awaitable[None]],
    ) -> None:
        self.chatbox_session_id = chatbox_session_id
        self.runtime = runtime
        self.workspace_root = workspace_root.resolve()
        self.history = ChatboxHistory(chatbox_session_id)
        self._on_terminal = on_terminal
        self._on_checkpoint = on_checkpoint
        self._lock = asyncio.Lock()
        self._subscriber: asyncio.Queue[BrokerItem] | None = None
        self._task: asyncio.Task[None] | None = None
        self._failure: PiRuntimeError | None = None
        self._stopping = False
        self._idle_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._stopping:
            raise ChatboxBrokerResyncError
        if self._task is None:
            self._task = asyncio.create_task(
                self._pump(),
                name=f"chatbox-event-pump-{self.chatbox_session_id}",
            )

    async def subscribe(self, after_revision: int) -> asyncio.Queue[BrokerItem]:
        async with self._lock:
            if self._stopping:
                raise ChatboxBrokerResyncError
            if self._subscriber is not None:
                raise ChatboxBrokerBusyError
            if self._failure is not None:
                raise self._failure
            try:
                pending = self.history.pending_after(after_revision)
            except ChatboxHistoryStaleError as exc:
                try:
                    await _run_history_operation(self.history.checkpoint)
                except Exception as checkpoint_error:
                    raise PiRuntimeError(
                        f"chatbox session {self.chatbox_session_id} checkpoint failed"
                    ) from checkpoint_error
                raise ChatboxBrokerResyncError from exc
            self._cancel_idle_task()
            queue: asyncio.Queue[BrokerItem] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
            for event in pending:
                queue.put_nowait(event)
            self._subscriber = queue
            return queue

    async def unsubscribe(self, queue: asyncio.Queue[BrokerItem] | None) -> None:
        if queue is None:
            return
        async with self._lock:
            if self._subscriber is queue:
                self._subscriber = None
                self._schedule_idle_stop()

    async def stop(self) -> None:
        self._stopping = True
        self._cancel_idle_task()
        task = self._task
        self._task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            if self._subscriber is not None:
                while not self._subscriber.empty():
                    self._subscriber.get_nowait()
                self._subscriber.put_nowait(ChatboxBrokerResyncError())
            self._subscriber = None

    async def checkpoint_for_shutdown(self) -> None:
        """Persist the projection and durable Pi checkpoint before process teardown."""

        await _run_history_operation(
            self.history.checkpoint,
            runtime_state="stopped",
            session_state="paused",
        )
        await self._on_checkpoint()

    async def record_admission(
        self,
        *,
        message: str | None,
        status: str,
        reason_code: str,
    ) -> None:
        """Persist a rejected/clarification turn in the browser projection only."""

        suffix = uuid.uuid4().hex
        events: list[dict[str, object]] = []
        if message is not None and message.strip():
            events.append(
                {
                    "type": "message_end",
                    "message": {
                        "id": f"admission-user-{suffix}",
                        "role": "user",
                        "content": [{"type": "text", "text": message}],
                    },
                }
            )
        events.append(
            {
                "type": "message_end",
                "message": {
                    "id": f"admission-platform-{suffix}",
                    "role": "platform",
                    "content": [
                        {
                            "type": "admission",
                            "status": status,
                            "reasonCode": reason_code,
                        }
                    ],
                },
            }
        )
        async with self._lock:
            for event in events:
                _revision, browser_event = await _run_history_operation(
                    self.history.apply,
                    event,
                )
                await self._publish(browser_event)
            await _run_history_operation(
                self.history.checkpoint,
                navigation_ready=True,
            )

    async def _pump(self) -> None:
        try:
            async for event in self.runtime.events():
                projected = project_event(event, self.workspace_root)
                if projected is None:
                    continue
                async with self._lock:
                    _revision, browser_event = await _run_history_operation(
                        self.history.apply,
                        projected,
                    )
                    if projected.get("type") == "agent_settled":
                        await self._on_checkpoint()
                    await self._publish(browser_event)
            if not self._stopping:
                raise PiRuntimeError(
                    f"pi runtime session {self.runtime.session_id} event stream ended"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, PiRuntimeError)
                else PiRuntimeError(
                    f"pi runtime session {self.runtime.session_id} event pump failed"
                )
            )
            async with self._lock:
                self._failure = failure
                await self._publish(failure)
                try:
                    await _run_history_operation(self.history.mark_dead)
                except Exception as history_error:
                    logger.error(
                        "Chatbox history failure session=%s error_type=%s",
                        self.chatbox_session_id,
                        type(history_error).__name__,
                    )
            logger.warning(
                "Chatbox event pump failed session=%s error_type=%s",
                self.chatbox_session_id,
                type(exc).__name__,
            )
            await self._on_terminal(True)

    async def _publish(self, item: BrokerItem) -> None:
        queue = self._subscriber
        if queue is None:
            return
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            if isinstance(item, dict):
                await _run_history_operation(self.history.checkpoint)
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(ChatboxBrokerResyncError())

    def _cancel_idle_task(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _schedule_idle_stop(self) -> None:
        self._cancel_idle_task()
        if self._stopping:
            return
        self._idle_task = asyncio.create_task(
            self._expire_disconnected_session(),
            name=f"chatbox-idle-expiry-{self.chatbox_session_id}",
        )

    async def _expire_disconnected_session(self) -> None:
        try:
            await asyncio.sleep(_DISCONNECTED_GRACE_SECONDS)
            await self._on_terminal(False)
        except asyncio.CancelledError:
            raise
