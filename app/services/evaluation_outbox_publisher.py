"""Lifespan-owned publisher for the evaluation dispatch outbox.

Wakes immediately after a backend replica starts and polls every second.
Claims up to 100 eligible rows per cycle using ``FOR UPDATE SKIP LOCKED``,
holds a 30-second publishing lease, sends one Celery task per row to the
``evaluation`` queue, and records success or exponential-backoff failure
(capped at 60 seconds). Expired leases are recovered automatically by the
repository's claim path; cancelled rows are skipped.

Runs in every backend replica. ``SKIP LOCKED`` plus leases make concurrent
publishers cooperate safely.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.repositories.evaluation_dispatch_repository import EvaluationDispatchRepository
from app.worker_tasks import EXECUTE_EVALUATION_DOCUMENT_TASK_NAME

if TYPE_CHECKING:
    from celery import Celery

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_BATCH_SIZE = 100
DEFAULT_LEASE_SECONDS = 30


class EvaluationOutboxPublisher:
    """Publish pending evaluation dispatch rows to the Celery evaluation queue."""

    def __init__(
        self,
        *,
        celery_app: "Celery",
        repository: EvaluationDispatchRepository | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        send_task: Callable[..., None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._celery_app = celery_app
        self._repository = repository or EvaluationDispatchRepository()
        self._poll_interval_seconds = max(0.1, poll_interval_seconds)
        self._batch_size = max(1, batch_size)
        self._lease_seconds = max(1, lease_seconds)
        self._send_task = send_task or self._default_send_task
        self._clock = clock or asyncio.get_event_loop().time
        self._stop_event: asyncio.Event | None = None

    def _default_send_task(self, task_id: str, result_id: str) -> None:
        self._celery_app.send_task(
            EXECUTE_EVALUATION_DOCUMENT_TASK_NAME,
            args=[result_id],
            task_id=task_id,
        )

    async def publish_once(self) -> int:
        """Claim a batch, dispatch each row, return the number published.

        Returns 0 when nothing was eligible or all attempts in the batch failed.
        """
        rows = await self._repository.claim_pending(
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        if not rows:
            return 0

        published = 0
        for row in rows:
            async with self._repository.publish_guard(row.id) as can_publish:
                if not can_publish:
                    continue

                try:
                    self._send_task(row.task_run_id, row.evaluation_result_id)
                except Exception as exc:  # noqa: BLE001 — broker / dispatch failure
                    logger.warning(
                        "evaluation dispatch publish failed for outbox=%s result=%s error_type=%s",
                        row.id,
                        row.evaluation_result_id,
                        type(exc).__name__,
                    )
                    try:
                        await self._repository.mark_publish_failed(
                            row.id,
                            error=str(exc),
                        )
                    except Exception as record_exc:  # noqa: BLE001
                        logger.error(
                            "failed to record publish failure for outbox=%s error_type=%s",
                            row.id,
                            type(record_exc).__name__,
                        )
                    continue

                try:
                    updated = await self._repository.mark_published(row.id)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "failed to record publish success for outbox=%s error_type=%s",
                        row.id,
                        type(exc).__name__,
                    )
                    updated = None

                if updated is not None:
                    published += 1
        return published

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Loop until ``stop_event`` (or the default internal event) is set."""
        if stop_event is None:
            if self._stop_event is None:
                self._stop_event = asyncio.Event()
            stop_event = self._stop_event

        # Immediate wake on startup so freshly created runs dispatch without
        # waiting for the first poll cycle.
        await self.publish_once()
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                await self.publish_once()
            except Exception as exc:  # noqa: BLE001 — publisher must not die
                logger.error(
                    "evaluation outbox publish cycle raised unexpectedly error_type=%s",
                    type(exc).__name__,
                )

    def request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()


async def run_publisher_until_stopped(
    publisher: EvaluationOutboxPublisher,
    *,
    ready: Awaitable[None] | None = None,
) -> None:
    """Convenience entrypoint used by the FastAPI lifespan.

    ``ready`` may be an awaitable that the lifespan resolves after registering
    the publisher so teardown can cancel it cleanly.
    """
    if ready is not None:
        try:
            await ready
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "publisher readiness await failed; continuing anyway error_type=%s",
                type(exc).__name__,
            )
    await publisher.run()
