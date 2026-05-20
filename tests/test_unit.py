"""
Unit tests for the CircuitBreaker class.
Run with: pytest tests/test_unit.py -v
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import CircuitBreaker, CircuitState

FALLBACK = {"response": "fallback", "tokens_used": 0}


async def fast_ok():
    return {"response": "ok", "tokens_used": 10}


async def slow_hang():
    await asyncio.sleep(60)
    return {"response": "never"}


async def instant_fail():
    raise RuntimeError("LLM API error 500")



# Tests


@pytest.mark.asyncio
async def test_closed_state_on_success():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=2)
    result = await cb.call(fast_ok(), FALLBACK)
    assert result["_circuit"] == "CLOSED"
    assert result["_fallback"] is False
    assert result["response"] == "ok"


@pytest.mark.asyncio
async def test_failure_increments_counter():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=0.1)
    await cb.call(slow_hang(), FALLBACK)
    assert cb._failure_count == 1
    assert cb._state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=0.1)
    for _ in range(3):
        await cb.call(slow_hang(), FALLBACK)
    assert cb._state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_returns_fallback_instantly():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=0.1)
    for _ in range(3):
        await cb.call(slow_hang(), FALLBACK)

    import time
    t0 = time.perf_counter()
    result = await cb.call(slow_hang(), FALLBACK)
    elapsed = time.perf_counter() - t0

    assert result["_fallback"] is True
    assert result["_circuit"] == "OPEN"
    assert elapsed < 0.1, f"Open circuit should be instant but took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_success_resets_failure_count():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=0.1)
    await cb.call(slow_hang(), FALLBACK)   # 1 failure
    await cb.call(fast_ok(), FALLBACK)     # success -> reset
    assert cb._failure_count == 0
    assert cb._state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_instant_exception_also_trips_breaker():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=5, request_timeout=2)
    await cb.call(instant_fail(), FALLBACK)
    await cb.call(instant_fail(), FALLBACK)
    assert cb._state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_half_open_closes_on_success():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1, request_timeout=0.05)
    # Trip the breaker
    for _ in range(2):
        await cb.call(slow_hang(), FALLBACK)
    assert cb._state == CircuitState.OPEN

    # Wait for recovery_timeout
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    # Probe with a good request
    result = await cb.call(fast_ok(), FALLBACK)
    assert cb._state == CircuitState.CLOSED
    assert result["_fallback"] is False


@pytest.mark.asyncio
async def test_stats_reflect_reality():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, request_timeout=0.05)
    await cb.call(fast_ok(), FALLBACK)
    await cb.call(slow_hang(), FALLBACK)
    stats = cb.stats()
    assert stats["total_calls"] == 2
    assert stats["total_failures"] == 1
    assert stats["failure_count"] == 1
