from __future__ import annotations

import pytest

from app.errors import EngineError, ErrorCode
from app.errors.retry import RetryConfig, RetryState, retry_with_backoff


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_retryable_error_until_success() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []
    retry_states: list[RetryState] = []

    async def _operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise EngineError(
                error_code=ErrorCode.ENGINE_TIMEOUT,
                message="engine timeout",
                engine_name="ocr",
            )
        return "ok"

    async def _sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    async def _on_retry(state: RetryState) -> None:
        retry_states.append(state)

    result = await retry_with_backoff(
        _operation,
        RetryConfig(max_retries=3, base_delay=1.0, max_delay=16.0, jitter=0.0),
        on_retry=_on_retry,
        sleep=_sleep,
    )

    assert result == "ok"
    assert calls["count"] == 3
    assert sleep_calls == [1.0, 2.0]
    assert [state.retry_count for state in retry_states] == [1, 2]
    assert all(state.max_retries == 3 for state in retry_states)


@pytest.mark.asyncio
async def test_retry_with_backoff_does_not_retry_non_retryable_error() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    async def _operation() -> str:
        calls["count"] += 1
        raise EngineError(
            error_code=ErrorCode.ENGINE_INVALID_RESPONSE,
            message="invalid response",
            engine_name="ocr",
        )

    async def _sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    with pytest.raises(EngineError) as exc_info:
        await retry_with_backoff(
            _operation,
            RetryConfig(max_retries=3, base_delay=1.0, max_delay=16.0, jitter=0.0),
            sleep=_sleep,
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_INVALID_RESPONSE
    assert calls["count"] == 1
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_retry_with_backoff_raises_after_max_retries() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    async def _operation() -> str:
        calls["count"] += 1
        raise EngineError(
            error_code=ErrorCode.ENGINE_UNREACHABLE,
            message="engine unreachable",
            engine_name="vlm",
        )

    async def _sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    with pytest.raises(EngineError) as exc_info:
        await retry_with_backoff(
            _operation,
            RetryConfig(max_retries=3, base_delay=1.0, max_delay=16.0, jitter=0.0),
            sleep=_sleep,
        )

    assert exc_info.value.error_code is ErrorCode.ENGINE_UNREACHABLE
    assert calls["count"] == 4
    assert sleep_calls == [1.0, 2.0, 4.0]
