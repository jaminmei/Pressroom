from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError

T = TypeVar("T")

RETRYABLE_ENGINE_ERRORS: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.ENGINE_TIMEOUT,
        ErrorCode.ENGINE_UNREACHABLE,
        ErrorCode.ENGINE_RATE_LIMITED,
    }
)


@dataclass(slots=True)
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 16.0
    jitter: float = 1.0
    retryable_errors: frozenset[ErrorCode] = RETRYABLE_ENGINE_ERRORS

    def next_delay_seconds(self, retry_count: int) -> float:
        if retry_count <= 0:
            return 0.0
        exponential = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
        jitter = float(random.uniform(0.0, self.jitter)) if self.jitter > 0 else 0.0
        return float(exponential + jitter)


@dataclass(slots=True)
class RetryState:
    retry_count: int
    max_retries: int
    next_retry_delay_seconds: float
    error: EngineError


RetryCallback = Callable[[RetryState], Awaitable[None]]
SleepFn = Callable[[float], Awaitable[None]]


async def retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    config: RetryConfig,
    *,
    on_retry: RetryCallback | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> T:
    attempts = config.max_retries + 1
    for attempt in range(attempts):
        try:
            return await func()
        except EngineError as error:
            if error.error_code not in config.retryable_errors:
                raise
            if attempt >= config.max_retries:
                raise

            retry_count = attempt + 1
            delay_seconds = config.next_delay_seconds(retry_count)
            if on_retry is not None:
                await on_retry(
                    RetryState(
                        retry_count=retry_count,
                        max_retries=config.max_retries,
                        next_retry_delay_seconds=delay_seconds,
                        error=error,
                    )
                )
            await sleep(delay_seconds)

    raise RuntimeError("retry_with_backoff exited unexpectedly")
