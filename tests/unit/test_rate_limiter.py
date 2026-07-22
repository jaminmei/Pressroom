"""Unit tests for app/services/rate_limiter.py — in-memory token-bucket rate limiter."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services.rate_limiter import RateLimiter, RateLimitExceededError

# ── Test 1: burst up to rate then rejected ──


class TestBurstLimit:
    @pytest.mark.asyncio()
    async def test_allows_up_to_rate_then_rejects(self) -> None:
        limiter = RateLimiter(rate_per_minute=3)
        for _ in range(3):
            await limiter.check("k1")
        with pytest.raises(RateLimitExceededError):
            await limiter.check("k1")

    @pytest.mark.asyncio()
    async def test_rejections_count_against_burst(self) -> None:
        """A rejected call should not consume a token."""
        limiter = RateLimiter(rate_per_minute=2)
        for _ in range(2):
            await limiter.check("k1")
        for _ in range(3):  # repeated rejects still fail
            with pytest.raises(RateLimitExceededError):
                await limiter.check("k1")


# ── Test 2: refill over time ──


class TestRefill:
    @pytest.mark.asyncio()
    async def test_refills_over_time(self) -> None:
        t = [1000.0]

        with patch("time.monotonic", lambda: t[0]):
            limiter = RateLimiter(rate_per_minute=6)  # 0.1 tokens / s
            # Exhaust 6 tokens (initial burst)
            for _ in range(6):
                await limiter.check("k1")
            with pytest.raises(RateLimitExceededError):
                await limiter.check("k1")
            # Advance 10 s → 1.0 tokens refilled
            t[0] = 1010.0
            await limiter.check("k1")  # ok
            with pytest.raises(RateLimitExceededError):
                await limiter.check("k1")  # only 1 refilled


# ── Test 3: independent buckets ──


class TestIndependentKeys:
    @pytest.mark.asyncio()
    async def test_different_keys_isolated(self) -> None:
        limiter = RateLimiter(rate_per_minute=2)
        # Exhaust k1
        for _ in range(2):
            await limiter.check("k1")
        with pytest.raises(RateLimitExceededError):
            await limiter.check("k1")
        # k2 is untouched
        await limiter.check("k2")
        await limiter.check("k2")
        with pytest.raises(RateLimitExceededError):
            await limiter.check("k2")


# ── Test 4: concurrent access race-free ──


class TestConcurrentAccess:
    @pytest.mark.asyncio()
    async def test_concurrent_calls_serialised(self) -> None:
        limiter = RateLimiter(rate_per_minute=1)

        async def do_check() -> str:
            await limiter.check("k1")
            return "ok"

        results = await asyncio.gather(
            do_check(),
            do_check(),
            return_exceptions=True,
        )
        successes = sum(1 for r in results if r == "ok")
        failures = sum(1 for r in results if isinstance(r, RateLimitExceededError))
        assert successes == 1, f"expected 1 success, got {successes}"
        assert failures == 1, f"expected 1 failure, got {failures}"


# ── Test 5: error raised (not silent False) ──


class TestErrorRaised:
    @pytest.mark.asyncio()
    async def test_raises_rate_limit_exceeded_error(self) -> None:
        limiter = RateLimiter(rate_per_minute=0)
        with pytest.raises(RateLimitExceededError):
            await limiter.check("any")
        # verify it's a ValueError subclass
        assert issubclass(RateLimitExceededError, ValueError)


# ── Test 6: constructor parameter ──


class TestConstructor:
    def test_accepts_rate_per_minute(self) -> None:
        r = RateLimiter(rate_per_minute=10)
        assert r._rate == 10
        assert r._buckets == {}


# ── Test 7: refill math ──


class TestRefillMath:
    @pytest.mark.asyncio()
    async def test_partial_refill_math(self) -> None:
        """Verify tokens refill at exactly rate/60 per second, capped at rate."""
        t = [0.0]

        with patch("time.monotonic", lambda: t[0]):
            limiter = RateLimiter(rate_per_minute=60)  # 1 token / s
            # Start with 60, consume 2
            await limiter.check("k1")
            await limiter.check("k1")
            # Advance 30 s → refill 30 tokens, but already at 58 → capped at 60
            t[0] = 30.0
            # Consume 60 calls (should work since refilled to 60)
            for _ in range(60):
                await limiter.check("k1")
            # Exhausted
            with pytest.raises(RateLimitExceededError):
                await limiter.check("k1")

    @pytest.mark.asyncio()
    async def test_refill_capped_at_rate(self) -> None:
        """After a long sleep, tokens must not exceed rate."""
        t = [0.0]

        with patch("time.monotonic", lambda: t[0]):
            limiter = RateLimiter(rate_per_minute=10)
            for _ in range(10):
                await limiter.check("k1")
            # Advance 9999 s → would be 1666 tokens without cap
            t[0] = 9999.0
            # Only 10 calls should succeed (capped at rate)
            for _ in range(10):
                await limiter.check("k1")
            with pytest.raises(RateLimitExceededError):
                await limiter.check("k1")
