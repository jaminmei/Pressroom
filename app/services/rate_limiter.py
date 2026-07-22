# This per-process token bucket is reset on restart and is not shared across
# replicas. Use a shared backend before horizontally scaling the API.

import asyncio
import time


class RateLimitExceededError(ValueError):
    pass


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.rate = rate_per_minute
        self.tokens = float(rate_per_minute)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / 60.0))
            self.last_refill = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class RateLimiter:
    def __init__(self, rate_per_minute: int) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._rate = rate_per_minute
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self._rate)
                self._buckets[key] = bucket
        if not await bucket.allow():
            raise RateLimitExceededError()
